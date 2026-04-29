from __future__ import annotations

import html
import json
from dataclasses import asdict
from pathlib import Path

from .pymol_script import StructureInput


def structure_format(path: Path) -> str:
    if path.suffix.lower() == ".pdb":
        return "pdb"
    return "mmcif"


def build_html_viewer(inputs: list[StructureInput], title: str, compare: bool = False) -> str:
    structures = [
        {
            **asdict(item),
            "path": str(item.path),
            "display_name": item.path.name,
            "format": structure_format(item.path),
            "data": item.path.read_text(encoding="utf-8"),
        }
        for item in inputs
    ]
    payload = json.dumps(structures)
    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <script src="https://cdn.jsdelivr.net/npm/3dmol@2.4.2/build/3Dmol-min.js"></script>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --line: #d9dee7;
      --text: #18202b;
      --muted: #657080;
      --blue: #2563eb;
      --orange: #d97706;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background: var(--bg);
      display: grid;
      grid-template-rows: auto 1fr;
    }}
    header {{
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 0 16px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      font-size: 16px;
      line-height: 1.2;
      margin: 0;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .controls {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    button {{
      height: 32px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      border-radius: 6px;
      padding: 0 10px;
      font: inherit;
      cursor: pointer;
    }}
    button:hover {{ border-color: #9aa5b5; }}
    main {{
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(180px, 260px) 1fr;
    }}
    aside {{
      min-width: 0;
      border-right: 1px solid var(--line);
      background: var(--panel);
      overflow: auto;
      padding: 12px;
    }}
    .file {{
      display: grid;
      grid-template-columns: 12px 1fr;
      gap: 8px;
      align-items: start;
      padding: 8px 0;
      border-bottom: 1px solid #edf0f4;
      font-size: 13px;
    }}
    .swatch {{
      width: 10px;
      height: 10px;
      margin-top: 4px;
      border-radius: 999px;
      background: var(--blue);
    }}
    .file:nth-child(2n) .swatch {{ background: var(--orange); }}
    .name {{
      overflow-wrap: anywhere;
      font-weight: 650;
    }}
    .role {{
      color: var(--muted);
      margin-top: 2px;
      font-size: 12px;
    }}
    #viewer {{
      position: relative;
      min-width: 0;
      min-height: 0;
      width: 100%;
      height: calc(100vh - 56px);
      background: #ffffff;
    }}
    @media (max-width: 760px) {{
      header {{
        height: auto;
        min-height: 56px;
        align-items: flex-start;
        flex-direction: column;
        padding: 10px 12px;
      }}
      .controls {{ justify-content: flex-start; }}
      main {{ grid-template-columns: 1fr; }}
      aside {{
        max-height: 136px;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }}
      #viewer {{ height: calc(100vh - 193px); min-height: 420px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{escaped_title}</h1>
    <div class="controls">
      <button type="button" data-action="all">All</button>
      <button type="button" data-action="cartoon">Cartoon</button>
      <button type="button" data-action="sticks">Sticks</button>
      <button type="button" data-action="surface">Surface</button>
      {compare_buttons(compare)}
    </div>
  </header>
  <main>
    <aside id="files"></aside>
    <div id="viewer"></div>
  </main>
  <script>
    const structures = {payload};
    const compareMode = {json.dumps(compare)};
    const colors = ["#2563eb", "#d97706", "#059669", "#c026d3", "#0891b2", "#dc2626"];
    const viewer = $3Dmol.createViewer("viewer", {{ backgroundColor: "white" }});
    const models = [];
    const files = document.querySelector("#files");

    structures.forEach((structure, index) => {{
      const item = document.createElement("div");
      item.className = "file";
      item.innerHTML = `<span class="swatch" style="background:${{colors[index % colors.length]}}"></span>
        <span><span class="name">${{escapeHtml(structure.display_name)}}</span><span class="role">${{escapeHtml(structure.role)}}</span></span>`;
      files.appendChild(item);

      const model = viewer.addModel(structure.data, structure.format);
      models.push(model);
    }});

    function applyStyle(mode = "cartoon", visible = "all") {{
      models.forEach((model, index) => {{
        const shouldShow = visible === "all" || structures[index].role === visible;
        model.setStyle({{}}, {{}});
        if (!shouldShow) return;
        const color = colors[index % colors.length];
        if (mode === "sticks") {{
          model.setStyle({{}}, {{ stick: {{ color, radius: 0.14 }} }});
        }} else if (mode === "surface") {{
          model.setStyle({{}}, {{ surface: {{ color, opacity: compareMode ? 0.58 : 0.8 }} }});
        }} else {{
          model.setStyle({{}}, {{ cartoon: {{ color, opacity: compareMode ? 0.82 : 1 }} }});
          model.setStyle({{ hetflag: true }}, {{ stick: {{ radius: 0.14 }} }});
        }}
      }});
      viewer.zoomTo();
      viewer.render();
    }}

    function escapeHtml(value) {{
      return String(value).replace(/[&<>"']/g, (char) => ({{
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;"
      }}[char]));
    }}

    document.querySelectorAll("button[data-action]").forEach((button) => {{
      button.addEventListener("click", () => {{
        const action = button.dataset.action;
        if (action === "reference" || action === "mobile") {{
          applyStyle("cartoon", action);
        }} else if (action === "all") {{
          applyStyle("cartoon", "all");
        }} else {{
          applyStyle(action, "all");
        }}
      }});
    }});

    applyStyle("cartoon", "all");
  </script>
</body>
</html>
"""


def compare_buttons(compare: bool) -> str:
    if not compare:
        return ""
    return """
      <button type="button" data-action="reference">Reference</button>
      <button type="button" data-action="mobile">Mobile</button>
    """
