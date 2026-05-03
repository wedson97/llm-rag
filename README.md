# Chatbot CBO

Chatbot local para consulta da **Classificação Brasileira de Ocupações (CBO)**, rodando 100% offline sem depender de APIs externas ou internet.

---

## Sumário

- [Como funciona](#como-funciona)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Uso](#uso)
- [Exemplos de perguntas](#exemplos-de-perguntas)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Configurações e ajustes](#configurações-e-ajustes)
- [Limitações conhecidas](#limitações-conhecidas)

---

## Como funciona

O sistema usa uma arquitetura **RAG (Retrieval-Augmented Generation)** com busca híbrida em três camadas.

### Fluxo completo por pergunta

```
Pergunta do usuário
        │
        ├─► Expansão da query (LLM)
        │     └─► gera termos profissionais relacionados
        │
        ├─► Busca por código numérico (prioridade máxima)
        │     └─► ex: "3518" → encontra família 3518 diretamente
        │
        ├─► Busca por frase exata (alta precisão)
        │     └─► ex: "agente de proteção de aeroporto" → chunk 5173
        │
        ├─► Busca por palavra-chave (fallback)
        │     └─► singular + capitalizado (programadores → Programador)
        │
        ├─► Busca semântica vetorial (bge-m3 + ChromaDB)
        │     └─► usa query enriquecida com histórico + expansão
        │
        └─► Chunks relevantes → Qwen 2.5 7B → Resposta
```

### Por que RAG e não fine-tuning?

Fine-tuning ensinaria o modelo a imitar o estilo dos dados, mas não a recuperar informações precisas (códigos, descrições, formações). O RAG mantém o LLM intacto e fornece apenas o trecho relevante do CBO como contexto — mais preciso, mais confiável, e os dados podem ser atualizados sem retreinar nada.

### As três camadas de busca

| Camada | Técnica | Quando é usada |
|---|---|---|
| 1ª | Código numérico | Query contém 4 dígitos (ex: `3171`, `5173-05`) |
| 2ª | Frase exata (substring) | Query tem frases com 10+ chars |
| 3ª | Semântica vetorial | Sempre, como complemento |

As camadas são combinadas e deduplicadas. Os resultados das camadas 1 e 2 aparecem **primeiro** no contexto enviado ao LLM — isso reduz alucinação, pois o modelo vê a informação mais relevante antes do ruído.

### Expansão de query

Para perguntas amplas como *"quais cargos existem em um hospital?"*, o sistema faz uma chamada rápida ao LLM antes da busca para expandir a query com termos profissionais relacionados:

```
"hospital" → "médico, enfermeiro, técnico de enfermagem, farmacêutico, fisioterapeuta..."
```

Esses termos enriquecem a busca semântica, encontrando famílias CBO que não mencionam "hospital" explicitamente mas são relevantes para o setor.

### Dois modos de resposta

O LLM opera em dois modos dependendo do tipo de pergunta:

- **Modo lookup** — pergunta sobre ocupação específica: responde só com o que está literalmente no contexto, sem inferir. Se não encontrar: *"Não encontrei no CBO fornecido."*
- **Modo associação** — pergunta sobre setor/estabelecimento: pode inferir quais ocupações do contexto se encaixam naquele ambiente, mas só usa códigos reais do contexto.

### Dados carregados

Duas fontes são combinadas no banco vetorial:

| Arquivo | Conteúdo | Chunks |
|---|---|---|
| `cbo.txt` | CSV com ~4.000 códigos e títulos (CODIGO;TITULO) | Agrupados por subgrupo (3 dígitos) |
| `cbo_completo.txt` | Extraído do PDF oficial (págs. 24–827) | Uma família por chunk — inclui descrição, formação e condições |

O `cbo_completo.txt` é a fonte mais rica: cada chunk tem o nome da família, todas as ocupações com sinônimos, descrição sumária das atividades, formação exigida e condições de trabalho.

### Histórico de conversa

O histórico dos últimos 3 turnos é mantido em memória para perguntas de acompanhamento. Quando o usuário usa pronomes (*"e o dele?"*, *"quem é quem?"*), o sistema:

1. Inclui as últimas mensagens do usuário e do assistente na query semântica
2. Extrai frases e keywords do **input atual** (não do histórico), evitando que o histórico polua a busca precisa

---

## Requisitos

- Python 3.10+
- [Ollama](https://ollama.com) instalado e rodando
- GPU com 5GB+ VRAM recomendado (testado com RTX 3050 6GB)
- Funciona em CPU, mas mais lento

### Modelos utilizados

| Modelo | Função | VRAM aprox. |
|---|---|---|
| `bge-m3` | Embeddings multilíngues para busca semântica | ~600 MB |
| `qwen2.5:7b` | LLM para geração de respostas e expansão de query | ~4.5 GB |

---

## Instalação

### 1. Baixar os modelos no Ollama

```bash
ollama pull bge-m3
ollama pull qwen2.5:7b
```

### 2. Instalar dependências Python

```bash
pip install -r requirements.txt
```

Dependências: `chromadb`, `ollama`, `pdfplumber`

---

## Uso

### Primeira vez (ou ao atualizar os dados)

```bash
# Passo 1: coloque o PDF oficial do CBO na pasta do projeto
# Arquivo: cbo_completo.pdf (828 páginas, edição 2010)

# Passo 2: extrair o conteúdo do PDF (páginas 24–827)
python extract_pdf.py

# Passo 3: processar os dados e gerar o banco vetorial
python ingest.py
```

O `ingest.py` lê automaticamente o `cbo.txt` (CSV) e o `cbo_completo.txt` (extraído do PDF), gera embeddings com o `bge-m3` e salva tudo no ChromaDB em `./db/`.

### Uso diário

```bash
python chat.py
```

Digite `sair`, `exit` ou `Ctrl+C` para encerrar.

---

## Exemplos de perguntas

### Lookup por código
```
Você: cbo 5173-05
Você: quem é o cbo 3171-10
Você: quais os cbos do codigo 3518
```

### Lookup por nome
```
Você: qual o cbo do barbeiro
Você: cbo de programador
Você: cbo do agente de proteção de aeroporto
```

### Detalhes de uma ocupação
```
Você: o que faz um vendedor pracista?
Você: qual a formação exigida para o programador de internet?
Você: qual a experiência necessária para esse cargo?
```

### Perguntas de acompanhamento (histórico)
```
Você: cbo de programador
Assistente: CBO 3171-05 - Programador de internet ...
Você: qual a experiência necessária?     ← usa o histórico
Você: e a escolaridade?                  ← continua no contexto
```

### Associação por setor/estabelecimento
```
Você: quais cargos existem em um supermercado?
Você: quais cbos podem trabalhar em hospital?
Você: me dê opções de cbo para um restaurante
```

---

## Estrutura do projeto

```
projeto_rhavy/
│
├── cbo.txt              ← CSV fonte: CODIGO;TITULO (~4.000 linhas)
├── cbo_completo.pdf     ← PDF oficial do CBO 2010 (828 páginas)
├── cbo_completo.txt     ← gerado pelo extract_pdf.py (não editar)
│
├── extract_pdf.py       ← extrai e estrutura o PDF em famílias CBO
├── ingest.py            ← lê os dados e popula o ChromaDB com embeddings
├── chat.py              ← o chatbot (loop de conversa)
├── debug_pdf.py         ← utilitário para inspecionar páginas do PDF
│
├── requirements.txt
└── db/                  ← banco vetorial ChromaDB (gerado automaticamente)
```

---

## Configurações e ajustes

Todas as configurações ficam no topo do `chat.py`:

### Trocar o modelo LLM

```python
# LLM_MODEL = "llama3.2:3b"   # mais leve, menor qualidade
# LLM_MODEL = "llama3.1:8b"   # alternativa ao Qwen
LLM_MODEL = "qwen2.5:7b"      # padrão — melhor balanço qualidade/VRAM
```

Trocar o LLM **não requer reingestar** — só `chat.py` muda.

### Ativar modo debug

```python
DEBUG = True   # exibe chunks recuperados e query expandida no terminal
```

Útil para diagnosticar por que uma pergunta não encontrou o resultado esperado.

### Ajustar precisão da busca semântica

```python
DISTANCE_THRESHOLD = 0.75  # menor = mais estrito, maior = mais permissivo
```

Valores menores filtram mais chunks irrelevantes mas podem perder resultados válidos. Valores maiores trazem mais contexto mas aumentam o ruído.

### Ajustar quantidade de resultados

```python
N_RESULTS = 10  # máximo de chunks enviados ao LLM por pergunta
```

---

## Limitações conhecidas

| Limitação | Causa | Contorno |
|---|---|---|
| Famílias sem descrição | Algumas páginas do PDF não foram extraídas corretamente | O CSV cobre os títulos; a descrição pode estar ausente para algumas famílias |
| Plural em português | `"programadores"` pode não bater com `"Programador"` em algumas situações | Use o singular; o sistema tenta normalizar automaticamente |
| Associações amplas (ex: "navio") | Algumas famílias marítimas estão no CSV mas sem descrição no PDF | O sistema faz o possível com os dados disponíveis |
| Títulos levemente incorretos | O LLM pode misturar o título principal com sinônimos | Temperature=0 minimiza, mas é uma limitação do modelo 7B |
| Velocidade | Cada pergunta envolve 2 chamadas ao LLM (expansão + resposta) | A expansão usa `num_predict=80` para ser rápida |
