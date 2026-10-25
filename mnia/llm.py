"""Motor Claude do MN-IA.

- Toda chamada recebe as regras da casa no system prompt.
- Respostas estruturadas são pedidas em JSON e validadas.
- Tokens e custo estimado ficam registrados por módulo.
- Sem chave de API (ou com MNIA_SIMULADO=1) usa a função `simulador`
  passada pelo módulo, para testar o fluxo inteiro sem gastar nada.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Callable

from .config import config
from .db import Custo, sessao
from .regras import texto_regras

log = logging.getLogger("mnia.llm")

# Preço estimado em US$ por milhão de tokens (entrada, saída).
# ATUALIZAR com a tabela oficial em https://docs.claude.com antes de usar
# os números em relatório para o cliente. Pode ser sobrescrito por variável
# de ambiente: MNIA_PRECO_<MODELO>=entrada,saida
PRECOS_ESTIMADOS = {
    "claude-haiku-5-5": (1.0, 5.0),
    "claude-sonnet-5-5": (3.0, 15.0),
    "claude-opus-5-5": (5.0, 25.0),
}


def _preco(modelo: str) -> tuple[float, float]:
    env = os.getenv("MNIA_PRECO_" + modelo.upper().replace("-", "_"))
    if env:
        a, b = env.split(",")
        return float(a), float(b)
    return PRECOS_ESTIMADOS.get(modelo, (3.0, 15.0))


class ErroLLM(RuntimeError):
    pass


def extrair_json(texto: str) -> Any:
    """Extrai o primeiro objeto/lista JSON de uma resposta."""
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass
    for abre, fecha in (("{", "}"), ("[", "]")):
        ini, fim = texto.find(abre), texto.rfind(fecha)
        if ini != -1 and fim > ini:
            try:
                return json.loads(texto[ini:fim + 1])
            except json.JSONDecodeError:
                continue
    raise ErroLLM("Resposta da IA sem JSON válido")


def _registrar_custo(modulo: str, modelo: str, entrada: int, saida: int) -> None:
    pe, ps = _preco(modelo)
    custo = entrada / 1e6 * pe + saida / 1e6 * ps
    try:
        with sessao() as s:
            s.add(Custo(modulo=modulo, modelo=modelo, tokens_entrada=entrada,
                        tokens_saida=saida, custo_usd=round(custo, 6)))
    except Exception as e:  # custo nunca derruba o fluxo
        log.warning("Falha ao registrar custo: %s", e)


_cliente = None


def _cliente_anthropic():
    global _cliente
    if _cliente is None:
        import anthropic
        _cliente = anthropic.Anthropic(api_key=config().anthropic_api_key)
    return _cliente


# Modelos 5.5 pensam por padrão e o raciocínio consome max_tokens. Para tarefas de
# redação/classificação com JSON, desligamos o raciocínio prévio ("between_tools").
_recusam_between_tools: set[str] = set()


def _criar(modelo: str, max_tokens: int, sistema: str, conteudo: str):
    import anthropic
    args = dict(model=modelo, max_tokens=max_tokens, system=sistema,
                messages=[{"role": "user", "content": conteudo}])
    if modelo not in _recusam_between_tools:
        try:
            return _cliente_anthropic().messages.create(
                **args, extra_body={"thinking": {"type": "between_tools"}})
        except anthropic.BadRequestError as e:
            if "thinking" not in str(e).lower():
                raise
            log.info("Modelo não aceita thinking=between_tools; seguindo com o padrão.")
            _recusam_between_tools.add(modelo)
    return _cliente_anthropic().messages.create(**args)


def chamar(
    *,
    modulo: str,
    tarefa: str,
    conteudo: str,
    modelo: str | None = None,
    max_tokens: int = 2000,
    json_saida: bool = True,
    simulador: Callable[[], Any] | None = None,
    tentativas: int = 3,
) -> Any:
    """Chama o Claude com as regras da casa.

    tarefa   -> instruções específicas do módulo (vão no system prompt)
    conteudo -> os dados a analisar (vão na mensagem do usuário)
    """
    cfg = config()
    modelo = modelo or cfg.modelo_redacao

    if cfg.modo_simulado:
        if simulador is None:
            raise ErroLLM(f"{modulo}: modo simulado sem simulador definido")
        return simulador()

    sistema = texto_regras() + "\n\n=== TAREFA ===\n" + tarefa
    if json_saida:
        sistema += "\n\nResponda SOMENTE com JSON válido, sem texto antes ou depois."

    ultimo_erro: Exception | None = None
    for i in range(tentativas):
        try:
            resp = _criar(modelo, max_tokens, sistema, conteudo)
            texto = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            _registrar_custo(modulo, modelo, resp.usage.input_tokens, resp.usage.output_tokens)
            if not json_saida:
                return texto
            try:
                return extrair_json(texto)
            except ErroLLM:
                log.warning("%s: resposta sem JSON (stop=%s, %d tokens): %r", modulo,
                            getattr(resp, "stop_reason", "?"), resp.usage.output_tokens, texto[:200])
                raise
        except Exception as e:  # rede, limite, JSON inválido
            ultimo_erro = e
            espera = 2 ** i * 3
            log.warning("%s: tentativa %d falhou (%s); nova tentativa em %ds", modulo, i + 1, e, espera)
            time.sleep(espera)
    raise ErroLLM(f"{modulo}: falhou após {tentativas} tentativas: {ultimo_erro}")
