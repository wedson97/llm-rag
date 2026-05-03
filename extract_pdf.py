import re
import sys
import os
import pdfplumber

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "cbo_completo.txt")
START_PAGE = 24
END_PAGE = 827

CODIGO_RE = re.compile(r"CÓDIGO\s+(\d{4})", re.IGNORECASE)
OCUPACAO_RE = re.compile(r"^(\d{4}-\d{2})\s+(.+)")
PAGE_NUM_RE = re.compile(r"^\d{1,3}$")

SECTION_HEADERS = {
    "titulo":    re.compile(r"^T[íi]TUL[Oo]$", re.IGNORECASE),
    "descricao": re.compile(r"^DESCRI", re.IGNORECASE),
    "formacao":  re.compile(r"^FORMA[çc]", re.IGNORECASE),
    "condicoes": re.compile(r"^C[Oo][Nn]DI[çc]", re.IGNORECASE),
    "skip":      re.compile(
        r"^(CÓDIGO\s+INT|CONSUL|ESTA\s+FAM|NOTAS|INSTITU|RECURS|PARTICIP|GLOSSÁR|nOTAS|CÓD)",
        re.IGNORECASE
    ),
}


def detectar_secao(linha):
    for nome, padrao in SECTION_HEADERS.items():
        if padrao.match(linha):
            return nome
    return None


def extrair_texto(caminho_pdf):
    paginas = []
    with pdfplumber.open(caminho_pdf) as pdf:
        for i, pagina in enumerate(pdf.pages[START_PAGE - 1 : END_PAGE]):
            if (i + 1) % 100 == 0:
                print(f"  Lendo página {START_PAGE + i}/{END_PAGE}...")
            texto = pagina.extract_text(layout=False)
            if texto:
                paginas.append(texto)
    return "\n".join(paginas)


def unir_hifenizados(linhas):
    resultado = []
    for linha in linhas:
        if resultado and resultado[-1].endswith("-"):
            resultado[-1] = resultado[-1][:-1] + linha
        else:
            resultado.append(linha)
    return resultado


def parsear_bloco(codigo, bloco):
    ficha = {
        "codigo": codigo,
        "familia": [],
        "ocupacoes": [],
        "descricao": [],
        "formacao": [],
        "condicoes": [],
    }

    secao = "familia"
    ocupacao_atual = None

    for bruto in bloco.splitlines():
        linha = bruto.strip()
        if not linha or PAGE_NUM_RE.match(linha):
            continue

        detectado = detectar_secao(linha)
        if detectado == "skip":
            secao = "skip"
            continue
        if detectado:
            if ocupacao_atual:
                ficha["ocupacoes"].append(ocupacao_atual)
                ocupacao_atual = None
            secao = detectado
            continue

        if secao == "skip":
            continue

        if secao == "familia":
            ficha["familia"].append(linha)

        elif secao == "titulo":
            m = OCUPACAO_RE.match(linha)
            if m:
                if ocupacao_atual:
                    ficha["ocupacoes"].append(ocupacao_atual)
                ocupacao_atual = f"{m.group(1)} - {m.group(2)}"
            elif ocupacao_atual:
                if ocupacao_atual.endswith("-"):
                    ocupacao_atual = ocupacao_atual[:-1] + linha
                else:
                    ocupacao_atual += " " + linha

        elif secao in ("descricao", "formacao", "condicoes"):
            ficha[secao].append(linha)

    if ocupacao_atual:
        ficha["ocupacoes"].append(ocupacao_atual)

    if not ficha["ocupacoes"] and not ficha["descricao"]:
        return None

    ficha["familia"] = " ".join(unir_hifenizados(ficha["familia"]))
    ficha["descricao"] = " ".join(unir_hifenizados(ficha["descricao"]))
    ficha["formacao"] = " ".join(unir_hifenizados(ficha["formacao"]))
    ficha["condicoes"] = " ".join(unir_hifenizados(ficha["condicoes"]))
    return ficha


def parsear(texto_completo):
    partes = CODIGO_RE.split(texto_completo)
    fichas = []
    for i in range(1, len(partes) - 1, 2):
        codigo = partes[i].strip()
        bloco = partes[i + 1] if i + 1 < len(partes) else ""
        ficha = parsear_bloco(codigo, bloco)
        if ficha:
            fichas.append(ficha)
    return fichas


def escrever_saida(fichas, caminho_saida):
    with open(caminho_saida, "w", encoding="utf-8") as f:
        for ficha in fichas:
            f.write(f"=== FAMÍLIA CBO {ficha['codigo']} ===\n")
            if ficha["familia"]:
                f.write(f"NOME: {ficha['familia']}\n")
            if ficha["ocupacoes"]:
                f.write("OCUPAÇÕES:\n")
                for occ in ficha["ocupacoes"]:
                    f.write(f"  {occ}\n")
            if ficha["descricao"]:
                f.write(f"DESCRIÇÃO: {ficha['descricao']}\n")
            if ficha["formacao"]:
                f.write(f"FORMAÇÃO: {ficha['formacao']}\n")
            if ficha["condicoes"]:
                f.write(f"CONDIÇÕES: {ficha['condicoes']}\n")
            f.write("\n")


def main():
    base = os.path.dirname(__file__)
    caminho_pdf = sys.argv[1] if len(sys.argv) > 1 else None

    if not caminho_pdf:
        for f in os.listdir(base):
            if f.endswith(".pdf"):
                caminho_pdf = os.path.join(base, f)
                break

    if not caminho_pdf or not os.path.exists(caminho_pdf):
        print("PDF não encontrado. Coloque o PDF na pasta ou passe o caminho:")
        print("  python extract_pdf.py caminho/para/cbo.pdf")
        return

    print(f"Extraindo páginas {START_PAGE}–{END_PAGE} de: {os.path.basename(caminho_pdf)}")
    texto_completo = extrair_texto(caminho_pdf)

    print("Parseando famílias...")
    fichas = parsear(texto_completo)

    escrever_saida(fichas, OUTPUT_FILE)
    print(f"\n{len(fichas)} famílias extraídas → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
