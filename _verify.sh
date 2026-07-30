set -e
apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq socat >/dev/null 2>&1
echo "socat: $(which socat)"
pip install -q --no-cache-dir typer rich pyyaml python-dotenv cryptography "mcp[cli]" pymodbus pyserial pytest 2>&1 | tail -2
echo "=== deps ready ==="
cd /src && PYTHONPATH=/src python -m pytest tests/test_modbus_rtu_live.py -v -rs -p no:cacheprovider 2>&1 | tail -25
