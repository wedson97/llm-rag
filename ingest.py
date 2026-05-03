import csv
import os
import re
import chromadb
import ollama
from collections import defaultdict

EMBED_MODEL = "bge-m3"
DB_DIR = os.path.join(os.path.dirname(__file__), "db")
DATA_DIR = os.path.dirname(__file__)

FAMILIA_RE = re.compile(r"^=== FAMÍLIA CBO (\d+) ===$")


def ler_txt_estruturado(caminho):
    """Lê cbo_completo.txt gerado pelo extract_pdf.py, retorna chunks por família."""
    fragmentos = []
    with open(caminho, "r", encoding="utf-8") as f:
        conteudo = f.read()

    blocos = re.split(r"\n(?==== FAMÍLIA CBO)", conteudo)
    for bloco in blocos:
        bloco = bloco.strip()
        if not bloco:
            continue
        m = FAMILIA_RE.match(bloco.splitlines()[0])
        codigo = m.group(1) if m else "GERAL"
        fragmentos.append({"id": f"familia_{codigo}", "text": bloco, "source": "cbo_completo.txt", "codigo": codigo})

    return fragmentos


def ler_csv(caminho):
    """Lê CSV CODIGO;TITULO e agrupa por subgrupo (3 dígitos)."""
    ocupacoes = []
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            with open(caminho, "r", encoding=enc) as f:
                leitor = csv.DictReader(f, delimiter=";")
                for linha in leitor:
                    codigo = (linha.get("CODIGO") or "").strip()
                    titulo = (linha.get("TITULO") or "").strip()
                    if codigo and titulo:
                        ocupacoes.append((codigo, titulo))
            break
        except (UnicodeDecodeError, KeyError):
            continue

    grupos = defaultdict(list)
    for codigo, titulo in ocupacoes:
        chave = codigo[:3] if len(codigo) >= 3 else codigo
        grupos[chave].append(f"{codigo} - {titulo}")

    fragmentos = []
    for chave, entradas in grupos.items():
        fragmentos.append({
            "id": f"csv_sub_{chave}",
            "text": f"Subgrupo CBO {chave}:\n" + "\n".join(entradas),
            "source": os.path.basename(caminho),
            "codigo": chave,
        })
    return fragmentos


def ingerir():
    cliente = chromadb.PersistentClient(path=DB_DIR)

    try:
        cliente.delete_collection("cbo")
        print("Coleção anterior removida.")
    except Exception:
        pass
    colecao = cliente.create_collection("cbo")

    todos_fragmentos = []

    for nome_arquivo in os.listdir(DATA_DIR):
        caminho = os.path.join(DATA_DIR, nome_arquivo)

        if nome_arquivo == "cbo_completo.txt":
            print(f"\nLendo {nome_arquivo} (estruturado por família)...")
            fragmentos = ler_txt_estruturado(caminho)
            print(f"  {len(fragmentos)} famílias encontradas")
            todos_fragmentos.extend(fragmentos)

        elif nome_arquivo.endswith(".csv") or (nome_arquivo.endswith(".txt") and nome_arquivo != "cbo_completo.txt"):
            print(f"\nLendo {nome_arquivo} (CSV)...")
            fragmentos = ler_csv(caminho)
            print(f"  {len(fragmentos)} subgrupos encontrados")
            todos_fragmentos.extend(fragmentos)

    if not todos_fragmentos:
        print("Nenhum arquivo encontrado. Rode extract_pdf.py primeiro.")
        return

    # Remove IDs duplicados
    ids_vistos = set()
    unicos = []
    for f in todos_fragmentos:
        if f["id"] not in ids_vistos:
            ids_vistos.add(f["id"])
            unicos.append(f)
    todos_fragmentos = unicos

    print(f"\nTotal de fragmentos: {len(todos_fragmentos)}")
    print("Gerando embeddings... isso pode levar alguns minutos.\n")

    tamanho_lote = 10
    todos_embeddings = []
    textos = [f["text"] for f in todos_fragmentos]

    for i in range(0, len(textos), tamanho_lote):
        lote = textos[i : i + tamanho_lote]
        resposta = ollama.embed(model=EMBED_MODEL, input=lote)
        todos_embeddings.extend(resposta.embeddings)
        concluidos = min(i + tamanho_lote, len(textos))
        print(f"  {concluidos}/{len(textos)} fragmentos processados")

    colecao.add(
        documents=textos,
        embeddings=todos_embeddings,
        ids=[f["id"] for f in todos_fragmentos],
        metadatas=[{"source": f["source"], "codigo": f["codigo"]} for f in todos_fragmentos],
    )

    print("\nIngestão concluída! Banco vetorial salvo em ./db")


if __name__ == "__main__":
    ingerir()
