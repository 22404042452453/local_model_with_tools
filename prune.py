"""
prune_model.py — Создаёт облегчённую версию MoE модели в Ollama

Что делает:
  1. Читает оригинальную модель из Ollama
  2. Находит GGUF файл
  3. Если есть llama-quantize — физически вырезает слои (настоящий pruning)
  4. Если нет — создаёт облегчённый Modelfile с оптимальными параметрами
  5. Регистрирует новую модель в Ollama
  6. Тестирует что она работает

Использование:
  python prune_model.py
  python prune_model.py --source gpt-oss:20b --name gpt-oss-lite --ctx 4096
  python prune_model.py --source gpt-oss:20b --prune-layers 20,21,22,23
  python prune_model.py --source gpt-oss:20b --quantize q4_0
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


# ── GPU / CPU Monitoring ──────────────────────────────────────────────────────

def get_gpu_info() -> dict | None:
    """Читает VRAM через nvidia-smi. Возвращает dict или None."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return None
        parts = [p.strip() for p in r.stdout.strip().split(",")]
        if len(parts) < 6:
            return None
        return {
            "name":        parts[0],
            "vram_total":  int(parts[1]),
            "vram_used":   int(parts[2]),
            "vram_free":   int(parts[3]),
            "gpu_util":    int(parts[4]),
            "temp":        int(parts[5]),
        }
    except Exception:
        return None


def get_ram_info() -> dict:
    """Читает RAM. Работает на Windows и Linux без psutil."""
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["wmic", "OS", "get", "FreePhysicalMemory,TotalVisibleMemorySize", "/value"],
                capture_output=True, text=True, timeout=5,
            )
            data = {}
            for line in r.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    data[k.strip()] = int(v.strip())
            total = data.get("TotalVisibleMemorySize", 0) // 1024  # KB → MB
            free  = data.get("FreePhysicalMemory", 0) // 1024
            return {"ram_total": total, "ram_used": total - free, "ram_free": free}
        except Exception:
            pass

    # Linux / fallback
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])
        total = info.get("MemTotal", 0) // 1024
        avail = info.get("MemAvailable", info.get("MemFree", 0)) // 1024
        return {"ram_total": total, "ram_used": total - avail, "ram_free": avail}
    except Exception:
        return {"ram_total": 0, "ram_used": 0, "ram_free": 0}


def print_system_status(label: str = ""):
    """Красиво выводит текущее состояние GPU и RAM."""
    header = f"📊 {label}" if label else "📊 Состояние системы"
    print(f"\n{header}")
    print("─" * 50)

    gpu = get_gpu_info()
    ram = get_ram_info()

    if gpu:
        vram_pct = (gpu["vram_used"] / gpu["vram_total"] * 100) if gpu["vram_total"] else 0
        bar = _bar(vram_pct)
        print(f"  GPU:  {gpu['name']}")
        print(f"  VRAM: {gpu['vram_used']:,} / {gpu['vram_total']:,} MB  ({vram_pct:.0f}%)  {bar}")
        print(f"  Free: {gpu['vram_free']:,} MB")
        print(f"  Load: {gpu['gpu_util']}%   Temp: {gpu['temp']}°C")
    else:
        print("  GPU:  не обнаружена или nvidia-smi недоступен")

    if ram["ram_total"]:
        ram_pct = (ram["ram_used"] / ram["ram_total"] * 100) if ram["ram_total"] else 0
        bar = _bar(ram_pct)
        print(f"  RAM:  {ram['ram_used']:,} / {ram['ram_total']:,} MB  ({ram_pct:.0f}%)  {bar}")
        print(f"  Free: {ram['ram_free']:,} MB")

    print("─" * 50)
    return gpu, ram


def monitor_model_load(model_name: str, duration: int = 30):
    """
    Запускает модель, мониторит GPU/RAM каждую секунду,
    показывает пиковое потребление.
    """
    print(f"\n🔍 Мониторинг загрузки '{model_name}' ({duration}s)...")
    print("   Отправляю тестовый запрос и замеряю ресурсы...\n")

    # Снимок ДО
    gpu_before = get_gpu_info()
    ram_before = get_ram_info()

    # Запускаем модель с коротким промптом (в фоне)
    proc = subprocess.Popen(
        ["ollama", "run", model_name, "Посчитай 2+2 и ответь одним числом"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )

    # Мониторим каждую секунду
    peak_vram = 0
    peak_ram  = 0
    samples   = []

    for i in range(duration):
        time.sleep(1)
        gpu = get_gpu_info()
        ram = get_ram_info()

        vram_now = gpu["vram_used"] if gpu else 0
        ram_now  = ram["ram_used"]

        if vram_now > peak_vram: peak_vram = vram_now
        if ram_now  > peak_ram:  peak_ram  = ram_now

        # Дельта от "до загрузки"
        vram_delta = vram_now - (gpu_before["vram_used"] if gpu_before else 0)
        ram_delta  = ram_now - ram_before["ram_used"]

        status = "⏳" if proc.poll() is None else "✓"
        print(f"   {status} [{i+1:2d}s]  VRAM: {vram_now:,} MB (+{max(0,vram_delta):,})  "
              f"RAM: {ram_now:,} MB (+{max(0,ram_delta):,})")

        samples.append({"vram": vram_now, "ram": ram_now, "vram_d": vram_delta, "ram_d": ram_delta})

        # Если процесс завершился — ещё пару секунд и стоп
        if proc.poll() is not None and i > 3:
            time.sleep(2)
            gpu = get_gpu_info()
            ram = get_ram_info()
            if gpu and gpu["vram_used"] > peak_vram: peak_vram = gpu["vram_used"]
            break

    # Результат
    try:
        stdout, stderr = proc.communicate(timeout=5)
        answer = stdout.strip()[:200]
    except Exception:
        proc.kill()
        answer = "(timeout)"

    vram_model = peak_vram - (gpu_before["vram_used"] if gpu_before else 0)
    ram_model  = peak_ram - ram_before["ram_used"]

    print(f"\n{'='*50}")
    print(f"📈 Результат мониторинга: {model_name}")
    print(f"{'='*50}")
    print(f"  Ответ модели:   {answer}")
    print(f"  VRAM до:        {gpu_before['vram_used']:,} MB" if gpu_before else "  VRAM: N/A")
    print(f"  VRAM пик:       {peak_vram:,} MB")
    print(f"  VRAM модель:    ~{max(0, vram_model):,} MB  ← столько заняла модель")
    print(f"  RAM до:         {ram_before['ram_used']:,} MB")
    print(f"  RAM пик:        {peak_ram:,} MB")
    print(f"  RAM модель:     ~{max(0, ram_model):,} MB  ← столько заняла модель")
    print(f"{'='*50}")

    return {"vram_model": vram_model, "ram_model": ram_model, "answer": answer}


def _bar(pct: float, width: int = 20) -> str:
    """Рисует ASCII прогресс-бар."""
    filled = int(width * pct / 100)
    empty  = width - filled
    color  = "🟢" if pct < 50 else ("🟡" if pct < 80 else "🔴")
    return f"{color} [{'█' * filled}{'░' * empty}]"


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: list[str], check=True, capture=True, **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=capture, text=True, check=check, **kw)


def ollama_running() -> bool:
    try:
        run(["ollama", "list"], check=True)
        return True
    except Exception:
        return False


def get_modelfile(source: str) -> str:
    r = run(["ollama", "show", source, "--modelfile"])
    return r.stdout


def get_model_info(source: str) -> dict:
    """Получает информацию о модели через ollama show."""
    r = run(["ollama", "show", source, "--modelfile"])
    info = {"raw": r.stdout, "from_line": "", "params": {}, "template": ""}

    for line in r.stdout.splitlines():
        if line.startswith("FROM "):
            info["from_line"] = line[5:].strip()
        elif line.startswith("PARAMETER "):
            parts = line.split(None, 2)
            if len(parts) == 3:
                info["params"][parts[1]] = parts[2]
        elif line.startswith("TEMPLATE "):
            info["template"] = line[9:]

    return info


def find_gguf_path(source: str) -> Path | None:
    """Ищет GGUF файл модели в стандартных путях Ollama."""
    info = get_model_info(source)
    from_path = info["from_line"]

    # Прямой путь к файлу
    if from_path and Path(from_path).exists():
        return Path(from_path)

    # Стандартные пути Ollama
    home = Path.home()
    ollama_dirs = [
        home / ".ollama" / "models",
        Path(os.getenv("OLLAMA_MODELS", "")) if os.getenv("OLLAMA_MODELS") else None,
        Path("C:/Users") / os.getenv("USERNAME", "") / ".ollama" / "models" if sys.platform == "win32" else None,
    ]

    for d in ollama_dirs:
        if d and d.exists():
            # Ищем GGUF в blobs
            blobs = d / "blobs"
            if blobs.exists():
                for f in blobs.iterdir():
                    if f.stat().st_size > 1_000_000_000:  # > 1GB = наверно модель
                        return f

    return None


def find_llama_quantize() -> Path | None:
    """Ищет llama-quantize в PATH или стандартных местах."""
    # В PATH
    q = shutil.which("llama-quantize") or shutil.which("llama-quantize.exe")
    if q:
        return Path(q)

    # Стандартные места
    candidates = [
        Path("D:/llama-cpp/llama-quantize.exe"),
        Path("C:/llama-cpp/llama-quantize.exe"),
        Path.home() / "llama-cpp" / "llama-quantize.exe",
        Path.home() / "llama.cpp" / "build" / "bin" / "llama-quantize",
        Path("/usr/local/bin/llama-quantize"),
    ]
    for c in candidates:
        if c.exists():
            return c

    return None


# ── Pruning ───────────────────────────────────────────────────────────────────

def prune_with_llama_quantize(
    gguf_path: Path,
    output_path: Path,
    prune_layers: str | None = None,
    quantize: str | None = None,
) -> bool:
    """
    Физический pruning через llama-quantize.

    prune_layers: "20,21,22,23" — вырезать эти слои
    quantize:     "q4_0", "q3_k_s" — дополнительно квантовать
    """
    quantize_bin = find_llama_quantize()
    if not quantize_bin:
        print("\n  ⚠  llama-quantize не найден.")
        print("     Скачай llama.cpp: https://github.com/ggml-org/llama.cpp/releases")
        print("     Распакуй в D:\\llama-cpp\\ и запусти скрипт снова.\n")
        return False

    cmd = [str(quantize_bin)]

    if prune_layers:
        cmd += ["--prune-layers", prune_layers]

    cmd += [str(gguf_path), str(output_path)]

    if quantize:
        cmd.append(quantize)
    else:
        cmd.append("copy")  # без перекванта, просто копируем с прунингом

    print(f"\n🔪 Pruning модели...")
    try:
        r = run(cmd, check=False)
        if r.returncode == 0:
            orig_size = gguf_path.stat().st_size / (1024**3)
            new_size  = output_path.stat().st_size / (1024**3)
            saved     = (1 - new_size / orig_size) * 100
            print(f"\n  ✓ Оригинал:  {orig_size:.1f} GB")
            print(f"  ✓ После обрезки: {new_size:.1f} GB")
            print(f"  ✓ Сэкономлено:   {saved:.0f}%\n")
            return True
        else:
            print(f"  ✗ Ошибка: {r.stderr}")
            return False
    except Exception as e:
        print(f"  ✗ Ошибка: {e}")
        return False


# ── Modelfile generation ──────────────────────────────────────────────────────

def create_modelfile(
    source: str,
    from_path: str | None = None,
    ctx: int = 4096,
    system_prompt: str | None = None,
) -> str:
    """
    Генерирует Modelfile с оптимальными параметрами для лёгкого запуска.
    """
    base = from_path or source

    lines = [
        f"FROM {base}",
        "",
        "# -- Optimization for low-end hardware --",
        f"PARAMETER num_ctx {ctx}",
        "PARAMETER num_gpu 99",
        "PARAMETER num_thread 4",
        "PARAMETER temperature 0.6",
        "PARAMETER repeat_penalty 1.1",
    ]

    if system_prompt:
        lines += [
            "",
            f'SYSTEM """{system_prompt}"""',
        ]

    return "\n".join(lines)


# ── Register in Ollama ────────────────────────────────────────────────────────

def register_model(name: str, modelfile_content: str) -> bool:
    """Создаёт модель в Ollama из Modelfile."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".modelfile",
                                     delete=False, encoding="utf-8") as f:
        f.write(modelfile_content)
        modelfile_path = f.name

    try:
        print(f"\n📦 Регистрируем модель '{name}' в Ollama...")
        r = run(["ollama", "create", name, "-f", modelfile_path], check=False)
        if r.returncode == 0:
            print(f"  ✓ Модель '{name}' создана!\n")
            return True
        else:
            print(f"  ✗ Ошибка: {r.stderr}")
            return False
    finally:
        os.unlink(modelfile_path)


def test_model(name: str) -> None:
    """Быстрый тест что модель отвечает."""
    print(f"🧪 Тестируем '{name}'...")
    try:
        r = run(
            ["ollama", "run", name, "Скажи одно слово: привет или пока"],
            check=False,
        )
        if r.returncode == 0:
            answer = r.stdout.strip()[:200]
            print(f"  ✓ Ответ: {answer}\n")
        else:
            print(f"  ⚠ Ответ не получен: {r.stderr[:200]}\n")
    except Exception as e:
        print(f"  ⚠ Ошибка теста: {e}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Создаёт облегчённую версию MoE модели в Ollama",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python prune_model.py
  python prune_model.py --source gpt-oss:20b --name gpt-oss-lite --ctx 2048
  python prune_model.py --prune-layers 20,21,22,23
  python prune_model.py --prune-layers 18,19,20,21,22,23 --quantize q4_0
        """,
    )
    parser.add_argument("--source",       default="gpt-oss:20b", help="Исходная модель в Ollama")
    parser.add_argument("--name",         default="gpt-oss-lite", help="Имя новой модели")
    parser.add_argument("--ctx",          type=int, default=4096, help="Размер контекста (default: 4096)")
    parser.add_argument("--prune-layers", default=None, help="Слои для удаления: '20,21,22,23'")
    parser.add_argument("--quantize",     default=None, help="Дополнительная квантизация: q4_0, q3_k_s, q2_k")
    parser.add_argument("--no-test",      action="store_true", help="Не тестировать после создания")
    parser.add_argument("--monitor",      action="store_true", help="Замерить GPU/RAM при загрузке модели")
    parser.add_argument("--monitor-time", type=int, default=30, help="Длительность мониторинга в секундах")
    parser.add_argument("--status",       action="store_true", help="Только показать текущее состояние GPU/RAM")
    args = parser.parse_args()

    print("=" * 60)
    print("🔧 MoE Model Pruner для Ollama")
    print("=" * 60)

    # Режим: только статус системы
    if args.status:
        print_system_status("Текущее состояние")
        sys.exit(0)

    # Проверки
    if not ollama_running():
        print("✗ Ollama не запущена. Запусти: ollama serve")
        sys.exit(1)

    # Показать состояние ДО
    print_system_status("ДО создания модели")

    # Инфо об оригинале
    print(f"\n📋 Исходная модель: {args.source}")
    info = get_model_info(args.source)
    print(f"   FROM: {info['from_line']}")
    for k, v in info["params"].items():
        print(f"   {k}: {v}")

    pruned_gguf = None

    # ── Физический pruning (если запрошен) ────────────────────────────────
    if args.prune_layers or args.quantize:
        gguf_path = find_gguf_path(args.source)

        if gguf_path:
            print(f"\n📁 GGUF найден: {gguf_path}")
            print(f"   Размер: {gguf_path.stat().st_size / (1024**3):.1f} GB")

            output_path = Path(f"D:/{args.name}.gguf")
            success = prune_with_llama_quantize(
                gguf_path,
                output_path,
                prune_layers=args.prune_layers,
                quantize=args.quantize,
            )
            if success:
                pruned_gguf = str(output_path)
            else:
                print("   Продолжаем без физического pruning...\n")
        else:
            print("\n  ⚠ GGUF файл не найден, продолжаем без pruning...")

    # ── Создаём Modelfile ─────────────────────────────────────────────────
    modelfile = create_modelfile(
        source    = args.source,
        from_path = pruned_gguf,
        ctx       = args.ctx,
    )

    print("📝 Modelfile:")
    print("-" * 40)
    for line in modelfile.splitlines():
        print(f"   {line}")
    print("-" * 40)

    # ── Регистрация ───────────────────────────────────────────────────────
    if not register_model(args.name, modelfile):
        sys.exit(1)

    # ── Тест ──────────────────────────────────────────────────────────────
    if not args.no_test:
        test_model(args.name)

    # ── Мониторинг GPU/RAM ────────────────────────────────────────────────
    if args.monitor:
        print("\n" + "=" * 60)
        print("📊 Мониторинг загрузки модели")
        print("=" * 60)

        # Замеряем оригинал
        print(f"\n── Оригинал: {args.source} ──")
        orig_stats = monitor_model_load(args.source, duration=args.monitor_time)

        # Ждём выгрузки модели из памяти
        print("\n⏳ Жду 10с пока модель выгрузится...")
        time.sleep(10)

        # Замеряем обрезанную
        print(f"\n── Обрезанная: {args.name} ──")
        lite_stats = monitor_model_load(args.name, duration=args.monitor_time)

        # Сравнение
        print(f"\n{'='*60}")
        print("📊 Сравнение: оригинал vs обрезанная")
        print(f"{'='*60}")
        print(f"  {'':20} {'Оригинал':>12} {'Обрезанная':>12} {'Экономия':>12}")
        print(f"  {'VRAM модели':20} {orig_stats['vram_model']:>10,} MB {lite_stats['vram_model']:>10,} MB "
              f"{max(0, orig_stats['vram_model']-lite_stats['vram_model']):>10,} MB")
        print(f"  {'RAM модели':20} {orig_stats['ram_model']:>10,} MB {lite_stats['ram_model']:>10,} MB "
              f"{max(0, orig_stats['ram_model']-lite_stats['ram_model']):>10,} MB")
        print(f"{'='*60}")
    else:
        # Просто показать состояние ПОСЛЕ
        print_system_status("ПОСЛЕ создания модели")

    # ── Итог ──────────────────────────────────────────────────────────────
    print("=" * 60)
    print(f"✅ Готово! Используй модель:")
    print(f"   ollama run {args.name}")
    print()
    print(f"   В .env проекта:")
    print(f"   CODER_BACKEND=ollama")
    print(f"   CODER_MODEL={args.name}")
    print(f"   CODER_BASE_URL=http://localhost:11434/v1")
    print("=" * 60)


if __name__ == "__main__":
    main()