import os
import re
import chromadb
import ollama

EMBED_MODEL = "bge-m3"
# LLM_MODEL = "llama3.1:8b"
LLM_MODEL = "qwen2.5:7b"
DB_DIR = os.path.join(os.path.dirname(__file__), "db")
N_RESULTS = 10
DEBUG = False  # mude para True para ver chunks e query expandida

SYSTEM_PROMPT = """Você é uma ferramenta de consulta ao CBO (Classificação Brasileira de Ocupações).

TIPO 1 — Pergunta sobre ocupação específica (código, descrição, formação, experiência):
- Responda SOMENTE com o que está literalmente no contexto. Nunca infira nem complemente.
- Copie códigos EXATAMENTE. Se não estiver no contexto: "Não encontrei no CBO fornecido."

TIPO 2 — Pergunta sobre quais cargos existem em um setor ou estabelecimento:
- Use o contexto para listar os cargos relevantes com seus códigos reais.
- Você pode inferir quais ocupações do contexto se encaixam naquele ambiente.
- Nunca invente códigos — use apenas os que aparecem no contexto.

Use o histórico para resolver pronomes ("ele", "esse cargo", "quem é quem" etc.).
Responda em português."""

DISTANCE_THRESHOLD = 0.75
STOPWORDS = {
    "qual", "quais", "cbo", "cbos", "de", "do", "da", "o", "a", "um", "uma",
    "é", "são", "para", "que", "em", "no", "na", "os", "as", "oque", "oq",
    "quem", "esse", "essa", "este", "esta", "isso", "aqui", "como", "mais",
    "faz", "tem", "fazer", "tais", "cargo", "nome", "grupo", "codigo",
    "subgrupo", "familia", "ocupacao", "ocupacoes", "algumas", "alguns",
    "opcoes", "podem", "pode", "existe", "existem", "liste", "lista",
    "todos", "todas", "sobre", "relacionados", "relacionadas", "associados",
    "trabalharia", "trabalha", "trabalham", "trabalhar", "atuam", "atua",
    "tipo", "tipos", "nesse", "nessa", "neste", "nesta", "numa", "esses",
}
CODE_RE = re.compile(r'\b(\d{4})(?:-\d{2})?\b')


def construir_query_busca(entrada_usuario, historico):
    recentes = []
    for m in historico[-4:]:
        if m["role"] == "user":
            recentes.append(m["content"])
        elif m["role"] == "assistant":
            recentes.append(m["content"][:200])
    recentes.append(entrada_usuario)
    return " ".join(recentes)


def extrair_palavras_chave(texto):
    palavras = re.findall(r'\w+', texto.lower())
    return [p for p in palavras if len(p) >= 5 and p not in STOPWORDS]


def extrair_frases(texto, min_palavras=2, max_palavras=4):
    """Extrai frases de 2-4 palavras para busca exata por substring."""
    tokens = texto.lower().split()
    frases = []
    for tamanho in range(max_palavras, min_palavras - 1, -1):
        for i in range(len(tokens) - tamanho + 1):
            frase = " ".join(tokens[i:i + tamanho])
            if len(frase) >= 10:
                frases.append(frase)
    return frases


EXPAND_PROMPT = """Você auxilia buscas no CBO (Classificação Brasileira de Ocupações).
Dado o contexto abaixo, liste APENAS títulos de cargo, atividades profissionais e setores econômicos relacionados.
NÃO inclua tecnologias, matérias ou áreas de conhecimento genéricas.
Responda com no máximo 8 termos separados por vírgula, sem explicações.

Consulta: {query}
Termos profissionais e setores:"""


def expandir_query(entrada_usuario):
    """Expande a query com termos relacionados usando o LLM."""
    try:
        resposta = ollama.generate(
            model=LLM_MODEL,
            prompt=EXPAND_PROMPT.format(query=entrada_usuario),
            options={"temperature": 0, "num_predict": 80},
        )
        return resposta["response"].strip()
    except Exception:
        return ""


def buscar(colecao, query, original=""):
    vistos = set()
    docs_frases = []
    docs_palavras = []

    def variantes_singular(termo):
        """Gera variantes singulares simples para palavras em português."""
        variantes = {termo, termo.capitalize()}
        if termo.endswith("es") and len(termo) > 6:
            raiz = termo[:-2]
            variantes.update({raiz, raiz.capitalize()})
        elif termo.endswith("s") and len(termo) > 5:
            raiz = termo[:-1]
            variantes.update({raiz, raiz.capitalize()})
        return variantes

    def buscar_por_substring(termo):
        """Busca por substring com variações de capitalização e plural."""
        resultados = []
        docs_vistos = set()
        for variante in variantes_singular(termo):
            try:
                res = colecao.get(where_document={"$contains": variante}, limit=4)
                for doc in res["documents"]:
                    if doc[:80] not in docs_vistos:
                        resultados.append(doc)
                        docs_vistos.add(doc[:80])
            except Exception:
                pass
        return resultados

    # Input original tem prioridade para frases/keywords (evita ruído do histórico)
    fonte_kw = original if original else query

    # 0. Códigos numéricos têm prioridade máxima (4 dígitos, ex: 3518, 5173-05)
    for codigo in CODE_RE.findall(fonte_kw):
        for doc in buscar_por_substring(codigo):
            chave = doc[:80]
            if chave not in vistos:
                docs_frases.append(doc)
                vistos.add(chave)

    # 1. Busca por frases (mais precisa) — vai para o topo do contexto
    for frase in extrair_frases(fonte_kw)[:6]:
        for doc in buscar_por_substring(frase):
            chave = doc[:80]
            if chave not in vistos:
                docs_frases.append(doc)
                vistos.add(chave)

    # 2. Busca por palavra-chave individual
    for palavra in extrair_palavras_chave(fonte_kw)[:4]:
        for doc in buscar_por_substring(palavra):
            chave = doc[:80]
            if chave not in vistos:
                docs_palavras.append(doc)
                vistos.add(chave)

    # 3. Busca semântica com query expandida pelo LLM
    expandida = expandir_query(original or query)
    entrada_semantica = f"{query} {expandida}".strip()
    if DEBUG:
        print(f"[DEBUG] Query expandida: {expandida[:150]}")
    resposta_embed = ollama.embed(model=EMBED_MODEL, input=[entrada_semantica])
    resultados_sem = colecao.query(
        query_embeddings=[resposta_embed.embeddings[0]],
        n_results=N_RESULTS,
        include=["documents", "distances"],
    )
    docs_semanticos = []
    # Se já temos resultados precisos (frase/keyword), limita ruído semântico
    limite_sem = 3 if (docs_frases or docs_palavras) else N_RESULTS
    for doc, dist in zip(resultados_sem["documents"][0], resultados_sem["distances"][0]):
        if len(docs_semanticos) >= limite_sem:
            break
        chave = doc[:80]
        if dist < DISTANCE_THRESHOLD and chave not in vistos:
            docs_semanticos.append(doc)
            vistos.add(chave)

    # Frases primeiro (mais específicas), depois keywords, depois semântica
    return (docs_frases + docs_palavras + docs_semanticos)[:N_RESULTS]


def main():
    cliente = chromadb.PersistentClient(path=DB_DIR)
    colecao = cliente.get_or_create_collection("cbo")

    total = colecao.count()
    if total == 0:
        print("Banco vetorial vazio. Execute 'python ingest.py' primeiro.")
        return

    print("=" * 55)
    print("  Chatbot CBO - Classificação Brasileira de Ocupações")
    print("=" * 55)
    print(f"  {total} subgrupos carregados")
    print("  Digite 'sair' para encerrar.\n")

    historico = []

    while True:
        try:
            entrada_usuario = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrando...")
            break

        if not entrada_usuario:
            continue
        if entrada_usuario.lower() in ("sair", "exit", "quit"):
            print("Encerrando...")
            break

        query_busca = construir_query_busca(entrada_usuario, historico)
        fragmentos = buscar(colecao, query_busca, original=entrada_usuario)

        if DEBUG:
            print(f"\n[DEBUG] {len(fragmentos)} fragmentos recuperados:")
            for f in fragmentos:
                print(f"  → {f[:120].strip()}")
            print()

        contexto = "\n\n".join(fragmentos) if fragmentos else "Nenhuma informação encontrada no CBO para essa consulta."

        mensagens = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *historico,
            {
                "role": "user",
                "content": f"=== CONTEXTO CBO (use APENAS isto) ===\n{contexto}\n=== FIM DO CONTEXTO ===\n\nPergunta: {entrada_usuario}",
            },
        ]

        print("\nAssistente: ", end="", flush=True)
        texto_resposta = ""

        for trecho in ollama.chat(model=LLM_MODEL, messages=mensagens, stream=True, options={"temperature": 0}):
            texto = trecho["message"]["content"]
            print(texto, end="", flush=True)
            texto_resposta += texto

        print("\n")

        historico.append({"role": "user", "content": entrada_usuario})
        historico.append({"role": "assistant", "content": texto_resposta})
        if len(historico) > 6:
            historico = historico[-6:]


if __name__ == "__main__":
    main()
