#!/bin/bash
set -e

# extract_pdf.py não usa Ollama — pula espera e pull de modelos
if [[ "$*" == *"extract_pdf.py"* ]]; then
    exec "$@"
fi

OLLAMA_URL="${OLLAMA_HOST:-http://localhost:11434}"

echo "Aguardando Ollama em $OLLAMA_URL..."
until python3 -c "
import urllib.request, sys
try:
    urllib.request.urlopen('$OLLAMA_URL/api/version', timeout=3)
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
    sleep 2
done
echo "Ollama disponivel."

pull_se_necessario() {
    local MODEL="$1"
    local JA_TEM
    JA_TEM=$(python3 -c "
import urllib.request, json, sys
try:
    r = urllib.request.urlopen('$OLLAMA_URL/api/tags', timeout=5)
    models = [m['name'] for m in json.loads(r.read()).get('models', [])]
    print('sim' if any('$MODEL' in m for m in models) else 'nao')
except Exception:
    print('nao')
" 2>/dev/null)

    if [ "$JA_TEM" = "sim" ]; then
        echo "Modelo $MODEL ja disponivel."
    else
        echo "Baixando modelo $MODEL... (pode levar varios minutos)"
        python3 -c "
import urllib.request, json, sys
req = urllib.request.Request(
    '$OLLAMA_URL/api/pull',
    data=json.dumps({'name': '$MODEL', 'stream': False}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST'
)
try:
    with urllib.request.urlopen(req, timeout=3600) as r:
        result = json.loads(r.read())
        print('  ' + result.get('status', 'concluido'))
except Exception as e:
    print('  erro ao baixar: ' + str(e))
    sys.exit(1)
"
        echo "Modelo $MODEL pronto."
    fi
}

pull_se_necessario "bge-m3"
pull_se_necessario "qwen2.5:7b"

exec "$@"
