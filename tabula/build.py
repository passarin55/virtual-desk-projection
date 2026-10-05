#!/usr/bin/env python3
"""Assemble the single-file TABULA-Ω page from src/.
   dist/tabula.html          — full document (served by tabula_host.py or opened directly)
   dist/tabula_artifact.html — body fragment for publishing (the publisher adds the document skeleton)
"""
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "src"
JS = ["20_core.js", "30_config.js", "40_host.js", "50_input.js", "55_gfx.js", "60_widgets_a.js", "62_widgets_b.js",
      "64_widgets_c.js", "70_engine.js", "75_render.js", "78_link.js", "80_calib.js", "85_scheme.js", "88_tribunal.js",
      "90_dossier.js", "95_ui.js", "99_main.js"]


def build():
    head = (SRC / "00_head.html").read_text()
    css = (SRC / "05_style.css").read_text()
    markup = (SRC / "10_markup.html").read_text()
    js = "\n".join(f"/* ---- {n} ---- */\n" + (SRC / n).read_text() for n in JS)
    js = js.replace("</script", "<\\/script")
    body = f"{markup}\n<!--TABULA_BOOT-->\n<script type=\"module\">\n{js}\n</script>\n"
    full = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            f"{head}<style>\n{css}</style>\n</head>\n<body>\n{body}</body>\n</html>\n")
    frag = f"{head}<style>\n{css}</style>\n{body}"
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "tabula.html").write_text(full)
    (dist / "tabula_artifact.html").write_text(frag)
    (dist / "_bundle.js").write_text(js)          # for `node --check`
    host = "".join((ROOT / "host" / n).read_text() for n in ["a_core.py", "b_input.py", "c_platform.py", "d_sense.py", "e_server.py"])
    (dist / "tabula_host.py").write_text(host)
    print(f"built: tabula.html {len(full)/1024:.0f} KB · artifact fragment {len(frag)/1024:.0f} KB · js {js.count(chr(10))} lines · host {host.count(chr(10))} lines")


if __name__ == "__main__":
    build()
