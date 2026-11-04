from __future__ import annotations

import logging
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_HEADER_ZONE_RATIO=0.14
DEFAULT_FOOTER_ZONE_RATIO=0.92
SCALE_SCAN_EXTRA_LINES=6
SCALE_CAPTION_SCAN_LINES=24
SCALE_CAPTION_MAX_CHARS=44
DOC_SCALE_SCAN_PAGES=3
DOC_SCALE_MAX_SENTENCE_CHARS=300
_QUALIFICADORES_GLOBAIS=(
    "exceto quando indicado", "exceto quando mencionado", "exceto quando de",
    "salvo indicacao", "salvo quando", "salvo se", "salvo mencao",
    "a menos que indicado", "a nao ser quando", "sao apresentad", "estao apresentad",
    "encontram-se apresentad", "valores expressos", "todos os valores",
    "sao expressos", "todos os valores",
)
_FIM_DE_FRASE = re.compile(r"[.;]\s")
_ROTULO_MONETARIOS=(
    "lucro", "receita", "ebitda", "despesa", "custo", "patrimonio",
    "divida", "caixa", "imposto", "tributo", "amortizacao", "depreciacao",
    "capex", "investimento", "dividendo", "juros", "resultado financeiro",
    "ativo", "passivo", "margem bruta", "margem liquida",
)
_UNIDADES_NAO_MONETARIAS=(
    "m3", "km", "unidades", "habitantes", "gwh", "mwh medio", "mwm",
    "dias", "economias", "ligacoes", "kwh",
)
_PRECO_UNITARIO=re.compile(r"r\$\s*/", re.IGNORECASE)
_SIMBOLO_MOEDA=re.compile(r"\b(?:r|us)\$", re.IGNORECASE)
FOOTER_REPEAT_RATIO=0.6
FOOTER_MIN_TOKENS=5
_SCALE_PATTERNS:list[tuple[re.Pattern[str], str, str | None]]=[
    (re.compile(r"R\$\s*bilh(?:oes|ao)", re.IGNORECASE), "bilhoes", "BRL"),
    (re.compile(r"R\$\s*milh(?:oes|ao)", re.IGNORECASE), "milhoes", "BRL"),
    (re.compile(r"R\$\s*MM\b", re.IGNORECASE), "milhoes", "BRL"),
    (re.compile(r"R\$\s*mil(?!h)\b", re.IGNORECASE), "mil", "BRL"),
    (re.compile(r"\bem\s+milhares\b", re.IGNORECASE), "mil", "BRL"),
    (re.compile(r"\bem\s+milh(?:oes|ao)\b", re.IGNORECASE), "milhoes", "BRL"),
    (re.compile(r"US\$\s*bilh(?:oes|ao)", re.IGNORECASE), "bilhoes", "USD"),
    (re.compile(r"US\$\s*milh(?:oes|ao)", re.IGNORECASE), "milhoes", "USD"),
    (re.compile(r"US\$\s*mil(?!h)\b", re.IGNORECASE), "mil", "USD"),
    (re.compile(r"\bGWh\b|\bMW\s*m(?:ed)?\b", re.IGNORECASE), "energia", None),
]

SCALE_LABELS={
    "mil":"R$ mil (milhares de reais)",
    "milhoes":"R$ milhoes",
    "bilhoes":"R$ bilhoes",
    "energia":"unidades de energia",
}

_USD_LABELS={
    "mil":"US$ mil (milhares de dolares)",
    "milhoes":"US$ milhoes",
    "bilhoes":"US$ bilhoes",
}

def strip_accents(text:str)->str:
    normalized=unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")

_TEM_DIGITO=re.compile(r"\d")

def _env_int(nome:str, padrao:int)->int:
    bruto=(os.getenv(nome) or "").strip()
    try:
        return int(bruto) if bruto else padrao
    except ValueError:
        logger.warning("%s=%r nao e inteiro; usando %s", nome, bruto, padrao)
        return padrao

def _parece_legenda(linha: str)->bool:
    texto=linha.strip().strip("()[]{}:;.-—\t")
    if not texto or len(texto) > SCALE_CAPTION_MAX_CHARS:
        return False
    return not _TEM_DIGITO.search(texto)

def _colapsar_letra_espacada(texto:str)->str:
    tokens=texto.split()
    if sum(1 for t in tokens if len(t)==1)<3:
        return texto
    return "".join(tokens)

def detect_document_scale(textos_paginas: list[str])->tuple[str|None,str|None]:
    encontradas: dict[str, str|None]={}
    for texto in textos_paginas[:DOC_SCALE_SCAN_PAGES]:
        if not texto:
            continue
        unido=re.sub(r"\s+", " ", texto.replace("\n", " "))
        for frase in _FIM_DE_FRASE.split(unido):
            if len(frase) > DOC_SCALE_MAX_SENTENCE_CHARS:
                continue
            achatada=strip_accents(frase).lower()
            if not any(q in achatada for q in _QUALIFICADORES_GLOBAIS):
                continue
            escala, moeda = detect_scale(frase)
            if escala is not None:
                encontradas.setdefault(escala, moeda)

    if not encontradas:
        return None, None
    if len(encontradas) > 1:
        logger.warning(
            "Documento declara mais de uma escala global (%s); heranca desativada",
            ", ".join(sorted(encontradas)),
        )
        return None, None
    escala=next(iter(encontradas))
    return escala, encontradas[escala]

def marcas_monetarias(textos_tabelas: list[str])->tuple[bool, list[str]]:
    unido=strip_accents(" ".join(textos_tabelas)).lower()
    if not unido.strip():
        return False, []

    marcas: list[str]=[]
    if _PRECO_UNITARIO.search(unido):
        return False, ["preco-unitario(R$/)"]

    if _SIMBOLO_MOEDA.search(unido):
        marcas.append("simbolo-moeda")
    marcas.extend(f"rotulo:{r}" for r in _ROTULO_MONETARIOS if r in unido)
    if not marcas:
        return False, []

    unidades = [u for u in _UNIDADES_NAO_MONETARIAS if u in unido]
    if unidades and len(unidades) > len(marcas):
        return False, [f"dominada-por:{','.join(unidades[:3])}"]+marcas
    return True, marcas

def detect_page_scale(header_text:str, body_text:str)->tuple[str|None, str|None]:
    linhas=body_text.splitlines()
    inicio="\n".join(linhas[:SCALE_SCAN_EXTRA_LINES])
    escala, moeda=detect_scale(header_text, inicio)
    if escala is not None:
        return escala, moeda
    limite=_env_int("SCALE_CAPTION_SCAN_LINES", SCALE_CAPTION_SCAN_LINES)
    for linha in linhas[SCALE_SCAN_EXTRA_LINES:limite]:
        if not _parece_legenda(linha):
            continue
        escala, moeda = detect_scale(linha)
        if escala is not None:
            return escala, moeda
    return None, None

def detect_scale(*texts: str)->tuple[str|None, str|None]:
    haystack=strip_accents(" ".join(t for t in texts if t))
    for pattern, scale, currency in _SCALE_PATTERNS:
        if pattern.search(haystack):
            return scale, currency

    for linha in haystack.splitlines():
        colapsada=_colapsar_letra_espacada(linha)
        if colapsada == linha:
            continue
        for pattern, scale, currency in _SCALE_PATTERNS:
            if pattern.search(colapsada):
                return scale, currency
    return None, None

def format_scale_label(scale:str|None, currency:str|None)->str:
    if scale is None:
        return "NAO DECLARADA NESTA PAGINA"
    if currency == "USD":
        return _USD_LABELS.get(scale, scale)
    return SCALE_LABELS.get(scale, scale)

_SUBSIDIARY_SECTION=re.compile(
    r"RESULTADO\s+POR\s+SUBSIDIARIA\s*[>:\-]\s*(.+?)\s*$",
    re.IGNORECASE|re.MULTILINE,
)

_CONSOLIDATED=re.compile(r"\bCONSOLIDAD[OA]\b", re.IGNORECASE)

_SECTION_HEADING=re.compile(
    r"^\s*ANEXO\s+[IVXLC]+\s*[-—:]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SUBSIDIARY_IN_ANNEX=re.compile(
    r"RESULTADO\s+POR\s+SUBSIDIARIA\s*[>:\-]\s*(.+?)\s*$", re.IGNORECASE
)
_CONSOLIDATED_ANNEX=re.compile(r"RESULTADO\s+CONSOLIDADO", re.IGNORECASE)
_TOP_LEVEL_SECTION=re.compile(
    r"^\s*\d{1,2}\.?\s+([A-Za-z].*?)\s*$", re.MULTILINE
)
_MULTI_ENTITY_SECTION=re.compile(
    r"\b(?:DRE|ATIVO|PASSIVO|BALANCO|RESULTADO|FLUXO)\b.*\bPOR\s+EMPRESA\b",
    re.IGNORECASE,
)
MULTI_ENTITY_SCOPE="multiplas empresas (a coluna define a entidade)"
_HEADING_MAX_TOKENS=6
_HEADING_MAX_DIGITS=4

@dataclass(frozen=True)
class ScopeRules:
    aliases:dict[str,str]
    def normalize(self, raw:str)->str:
        key=re.sub(r"\s+", " ", strip_accents(raw).upper().strip())
        if key in self.aliases:
            return self.aliases[key]
        base=re.sub(r"\s*\(.*?\)\s*$", "", key).strip()
        if base and base in self.aliases:
            return self.aliases[base]
        return base or key

def load_scope_rules(config_path: Path, company:str)->ScopeRules:
    try:
        import yaml
    except ImportError:
        logger.warning(
            "PyYAML não está instalado."
        )
        return ScopeRules(aliases={})

    if not config_path.exists():
        logger.warning(
            "Configuração de aceso não encontrada em %s; usando o nome da entidade sem alias ", config_path
        )
        return ScopeRules(aliases={})

    try:
        data=yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.exception(" Falha ao ler a configuração de escopo %s", config_path)
        return ScopeRules(aliases={})
    companies=data.get("companies", {}) or {}
    wanted=strip_accents(company).upper()
    for name, cfg in companies.items():
        if strip_accents(str(name)).upper() == wanted:
            raw_aliases=(cfg or {}).get("aliases", {}) or {}
            aliases={
                re.sub(r"\s+", " ", strip_accents(str(k)).upper().strip()): str(v)
                for k, v in raw_aliases.items()
            }
            return ScopeRules(aliases=aliases)
    return ScopeRules(aliases={})

def detect_section_and_scope(
        header_text:str,
        rules:ScopeRules,
)->tuple[str|None, str|None, bool]:
    if not header_text:
        return None, None, False

    flat = strip_accents(header_text)
    section_title=None
    scope=None
    heading_match=_SECTION_HEADING.search(flat)
    numbered_match=_TOP_LEVEL_SECTION.search(flat)
    starts_new_section=heading_match is not None or numbered_match is not None
    if heading_match:
        annex_body=heading_match.group(1).strip()
        if _MULTI_ENTITY_SECTION.search(annex_body):
            scope=MULTI_ENTITY_SCOPE
        elif subsidiary := _SUBSIDIARY_IN_ANNEX.search(annex_body):
            scope=rules.normalize(subsidiary.group(1).strip())
        elif _CONSOLIDATED_ANNEX.search(annex_body):
            scope="consolidado"
    else:
        match=_SUBSIDIARY_SECTION.search(flat)
        if match:
            entity=match.group(1).strip()
            if _MULTI_ENTITY_SECTION.search(entity):
                scope=MULTI_ENTITY_SCOPE
            else:
                scope=rules.normalize(entity)
    if scope is None and numbered_match:
        scope=_scope_from_named_entity(numbered_match.group(1), rules)
    if heading_match:
        section_title=heading_match.group(0).strip()
    else:
        candidates=[
            line.strip()
            for line in header_text.splitlines()
            if line.strip() and _is_titleish(line)
        ]
        if candidates:
            section_title=max(candidates, key=len)

    if scope is None and _has_consolidated_heading(header_text):
        scope="consolidado"

    return section_title, scope, starts_new_section

def _scope_from_named_entity(section_title:str, rules:ScopeRules)->str|None:
    if not rules.aliases:
        return None
    haystack=re.sub(r"\s+", " ", section_title.upper())
    best: str|None=None
    best_len=0
    for key, value in rules.aliases.items():
        if key == "CONSOLIDADO":
            continue
        if key in haystack and len(key) > best_len:
            best, best_len = value, len(key)
    return best

def _has_consolidated_heading(header_text:str)->bool:
    for line in header_text.splitlines():
        stripped=line.strip()
        if not stripped or not _CONSOLIDATED.search(strip_accents(stripped)):
            continue
        if len(stripped.split()) > _HEADING_MAX_TOKENS:
            continue
        if sum(1 for ch in stripped if ch.isdigit()) > _HEADING_MAX_DIGITS:
            continue
        return True
    return False

def  _is_titleish(line:str)->bool:
    letters=[ch for ch in line if ch.isalpha()]
    if len(letters) < 6:
        return False
    upper=sum(1 for ch in letters if ch.isupper())
    return upper / len(letters) >= 0.7

_PAGE_LABEL=re.compile(r"(?<!\d)(\d{1,4})(?!\d)")

def build_footer_blacklist(footer_texts:list[str], total_pages: int)->set[str]:
    if total_pages <= 0:
        return set()

    counter: Counter[str]=Counter()
    for text in footer_texts:
        for line in text.splitlines():
            normalized=_normalize_footer_line(line)
            if normalized:
                counter[normalized] += 1

    threhold=max(2, int(total_pages * FOOTER_REPEAT_RATIO))
    blacklist={line for line, count in counter.items() if count >= threhold}
    if blacklist:
        logger.info(
            "Linha de exclusão do rodapé: %s linhas repetidas em %s paginas",
            len(blacklist),
            total_pages,
        )
    return blacklist

def _normalize_footer_line(line:str) -> str | None:
    stripped=line.strip()
    if not stripped:
        return None
    without_numbers = _PAGE_LABEL.sub("", stripped)
    tokens=without_numbers.split()
    if len(tokens) < FOOTER_MIN_TOKENS:
        return None
    letters=[ch for ch in without_numbers if ch.isalpha()]
    if not letters:
        return None
    if sum(1 for ch in letters if ch.isupper()) / len(letters) < 0.7:
        return None
    return re.sub(r"\s+", " ", strip_accents(without_numbers).upper()).strip()

def extract_printed_page_label(footer_text: str) -> str | None:
    if not footer_text:
        return None
    numbers=_PAGE_LABEL.findall(footer_text)
    if not numbers:
        return None
    for candidate in reversed(numbers):
        if 0 < int(candidate) < 2000:
            return candidate

def remove_blacklisted_lines(text:str, blacklist: set[str])->str:
    if not blacklist:
        return text

    kept=[]
    for line in text.splitlines():
        normalized=_normalize_footer_line(line)
        if normalized and normalized in blacklist:
            continue
        kept.append(line)
    return "\n".join(kept)

@dataclass(frozen=True)
class PageContext:
    section_title:str|None
    scope: str|None
    scale: str|None
    currency: str|None
    printed_page_label:str|None
    column_labels: list[str]
    scale_source:str|None=None

def build_context_preamble(
    company:str,
    year:int,
    quarter: str,
    doc_type:str,
    page_number:int,
    context: PageContext,
) -> str:
    page_ref=f"Pagina {page_number}"
    if context.printed_page_label and context.printed_page_label != str(page_number):
        page_ref+=f" (impressa: {context.printed_page_label})"
    lines=[
        f"[Empresa: {company} | Documento: {doc_type} {quarter}{str(year)[-2:]} | {page_ref}]"
    ]
    if context.section_title:
        lines.append(f"[Secao: {context.section_title}]")

    scope_label=context.scope or "NAO DECLARADO NESTA PAGINA"
    scale_label=format_scale_label(context.scale, context.currency)
    if context.scale is not None and context.scale_source == "documento":
        scale_label+=" (nota de unidades do documento, nao desta pagina)"
    third=f"[Escopo: {scope_label} | Escala: {scale_label}"
    if context.column_labels:
        third+= " | Colunas: " + " | ".join(context.column_labels)
    third+= "]"
    lines.append(third)
    return "\n".join(lines)
