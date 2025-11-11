# -*- coding: utf-8 -*-
"""
GUI simples para coletar artefatos de páginas (útil p/ SPAs):
- <out>/requests.html               (HTML cru via requests)
- <out>/requests_hrefs_sample.txt   (amostra de hrefs no HTML cru)
- <out>/rendered.html               (DOM final após JS - Playwright)
- <out>/screenshot.png              (print da tela)
- <out>/page.har                    (tráfego de rede com conteúdo embutido, quando suportado)
- <out>/anchors.txt                 (anchors do DOM renderizado)
- <out>/guess_links.txt             (links “chutados” por padrões de slug)

Deps:
  pip install requests playwright
  python -m playwright install chromium
"""

import os
import re
import sys
import queue
import threading
import pathlib
from urllib.parse import urljoin, urlparse

import requests
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124 Safari/537.36")

# ----------------------- Helpers -----------------------
def save_text(path: pathlib.Path, text: str, enc="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=enc)

def abs_url(href: str, base: str) -> str | None:
    if not href:
        return None
    h = href.strip()
    if h.startswith("#") or h.lower().startswith("javascript:"):
        return None
    if urlparse(h).scheme in ("http", "https"):
        return h
    return urljoin(base, h)

# ----------------------- Coleta (requests) -----------------------
def step_requests(url: str, outdir: pathlib.Path, log):
    r = requests.get(url, timeout=60, headers={"User-Agent": UA})
    r.raise_for_status()
    save_text(outdir / "requests.html", r.text)
    log(f"✓ requests.html salvo ({len(r.text)} bytes)")

    hrefs = re.findall(r'href=["\']([^"\']+)["\']', r.text, flags=re.I)
    sample = "\n".join(hrefs[:100])
    save_text(outdir / "requests_hrefs_sample.txt", sample)
    log(f"✓ requests_hrefs_sample.txt salvo ({min(100, len(hrefs))} hrefs)")

# ----------------------- Coleta (Playwright) -----------------------
def step_playwright(url: str, outdir: pathlib.Path, log):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        log("• Playwright não disponível. Pulei a etapa JS.")
        log(f"  Detalhe: {e}")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Nem todas as versões aceitam record_har_content="embed"
        ctx_kwargs = {"user_agent": UA}
        try:
            ctx = browser.new_context(
                **ctx_kwargs,
                record_har_path=str(outdir / "page.har"),
                record_har_content="embed",
            )
            har_ok = True
        except TypeError:
            # Fallback: grava HAR sem conteúdo embutido
            ctx = browser.new_context(
                **ctx_kwargs,
                record_har_path=str(outdir / "page.har"),
            )
            har_ok = False

        page = ctx.new_page()

        log("→ Abrindo no Chromium headless…")
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        try:
            page.wait_for_load_state("networkidle", timeout=60_000)
        except Exception:
            pass  # alguns sites nunca “param” a rede

        # DOM renderizado
        save_text(outdir / "rendered.html", page.content())
        log("✓ rendered.html salvo")

        # Screenshot
        page.screenshot(path=str(outdir / "screenshot.png"), full_page=True)
        log("✓ screenshot.png salvo")

        # Anchors do DOM final
        anchors = page.locator("a[href]").all()
        lines = []
        seen = set()
        for a in anchors:
            try:
                href = a.get_attribute("href") or ""
                text = (a.inner_text() or a.get_attribute("title") or a.get_attribute("aria-label") or "").strip()
                url_abs = abs_url(href, url)
                if not url_abs or url_abs in seen:
                    continue
                seen.add(url_abs)
                lines.append(f"{text[:120]} => {url_abs}")
            except Exception:
                pass
        save_text(outdir / "anchors.txt", "\n".join(lines))
        log(f"✓ anchors.txt salvo ({len(lines)} anchors únicos)")

        # Heurística de links candidatos (seleção/edital/chamada)
        guess = []
        for line in lines:
            try:
                href = line.split("=>", 1)[1].strip()
            except Exception:
                continue
            if re.search(r"/(selec|sele[cç][aã]o|chamad|edital)", href, flags=re.I):
                guess.append(href)
            elif re.search(r"/[a-z0-9-]{6,}$", href) and urlparse(href).netloc == urlparse(url).netloc:
                guess.append(href)
            elif "slug=" in href:
                guess.append(href.replace("/slug=", "/"))
        guess = sorted(set(guess))
        save_text(outdir / "guess_links.txt", "\n".join(guess))
        log(f"✓ guess_links.txt salvo ({len(guess)} candidatos)")

        ctx.close()
        browser.close()
        if har_ok:
            log("✓ page.har salvo (com conteúdo embutido).")
        else:
            log("✓ page.har salvo (sem conteúdo embutido).")

# ----------------------- Worker -----------------------
def run_collector(url: str, outdir: str, log, done_cb):
    out = pathlib.Path(outdir)
    try:
        log(f"URL: {url}")
        log(f"Pasta de saída: {out.resolve()}")
        step_requests(url, out, log)
        step_playwright(url, out, log)
        log("✔ Conclusão: artefatos salvos com sucesso.")
        done_cb(True, None)
    except Exception as e:
        log(f"✗ Erro: {e}")
        done_cb(False, e)

# ----------------------- GUI (Tkinter) -----------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Coletor de Páginas (debug SPA)")
        self.geometry("720x520")

        self.url_var = tk.StringVar(value="https://preprod-chamadas.funbio.org.br/")
        self.out_var = tk.StringVar(value=str(pathlib.Path.cwd() / "out_coleta"))

        frm_url = ttk.Frame(self); frm_url.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Label(frm_url, text="URL da página:").pack(anchor="w")
        ttk.Entry(frm_url, textvariable=self.url_var).pack(fill="x")

        frm_dir = ttk.Frame(self); frm_dir.pack(fill="x", padx=12, pady=6)
        ttk.Label(frm_dir, text="Pasta de saída:").pack(anchor="w")
        row = ttk.Frame(frm_dir); row.pack(fill="x")
        ttk.Entry(row, textvariable=self.out_var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Escolher…", command=self.choose_dir).pack(side="left", padx=6)

        frm_btn = ttk.Frame(self); frm_btn.pack(fill="x", padx=12, pady=(6, 6))
        self.btn_go = ttk.Button(frm_btn, text="Coletar", command=self.on_go); self.btn_go.pack(side="left")
        ttk.Button(frm_btn, text="Abrir pasta", command=self.open_dir).pack(side="left", padx=6)

        frm_log = ttk.Frame(self); frm_log.pack(fill="both", expand=True, padx=12, pady=(6, 12))
        ttk.Label(frm_log, text="Log:").pack(anchor="w")
        self.txt = tk.Text(frm_log, height=18); self.txt.pack(fill="both", expand=True)
        self.txt.configure(state="disabled")

        self.q = queue.Queue()
        self.after(100, self._drain_queue)
        self.thread = None

    def choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.out_var.get() or os.getcwd())
        if d:
            self.out_var.set(d)

    def log(self, msg: str):
        self.q.put(msg)

    def _append_log(self, msg: str):
        self.txt.configure(state="normal")
        self.txt.insert("end", msg + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _drain_queue(self):
        try:
            while True:
                self._append_log(self.q.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._drain_queue)

    def open_dir(self):
        path = pathlib.Path(self.out_var.get()).resolve()
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')

    def on_go(self):
        url = self.url_var.get().strip()
        out = self.out_var.get().strip()
        if not url:
            messagebox.showwarning("Atenção", "Informe a URL.")
            return
        if self.thread and self.thread.is_alive():
            messagebox.showinfo("Aguarde", "Uma coleta já está em andamento.")
            return
        self.btn_go.config(state="disabled")
        self.txt.configure(state="normal"); self.txt.delete("1.0", "end"); self.txt.configure(state="disabled")

        def done_cb(ok, err):
            self.btn_go.config(state="normal")
            if ok:
                self.log("Pronto! Abra a pasta e me envie os arquivos principais (page.har, rendered.html e requests.html).")
            else:
                self.log(f"Falhou: {err}")

        self.thread = threading.Thread(target=run_collector, args=(url, out, self.log, done_cb), daemon=True)
        self.thread.start()

if __name__ == "__main__":
    App().mainloop()
