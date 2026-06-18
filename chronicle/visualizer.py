"""HTML UI for Chronicle execution graph visualization."""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from chronicle.execution_graph import ExecutionGraph

_KIND_COLORS = {
    "llm": "#3b82f6",
    "tool": "#f59e0b",
    "custom": "#8b5cf6",
}


def _envelope_summary(envelope) -> dict[str, Any]:
    env = envelope
    full_envelope = json.loads(env.model_dump_json())
    detail: dict[str, Any] = {
        "envelope_id": env.envelope_id,
        "short_id": env.envelope_id[:8],
        "boundary_id": env.node_id,
        "boundary_kind": env.boundary_kind,
        "invocation_index": env.invocation_index,
        "sequence": env.sequence,
        "parent_envelope_id": env.parent_envelope_id,
        "parent_short_id": env.parent_envelope_id[:8] if env.parent_envelope_id else None,
        "kind_color": _KIND_COLORS.get(env.boundary_kind, "#6b7280"),
        "full_envelope": full_envelope,
        "messages": env.input_state.messages,
        "graph_state": env.input_state.graph_state,
        "system_prompt": env.input_state.system_prompt,
        "tool_calls": [tc.model_dump() for tc in env.action_result.tool_calls],
        "completion": env.action_result.completion,
        "finish_reason": env.action_result.finish_reason,
        "raw_response": env.action_result.raw_response,
        "model_version": env.metadata.model_version,
        "build_id": env.metadata.build_id,
    }
    if env.action_result.tool_calls:
        tc = env.action_result.tool_calls[0]
        detail["headline"] = f"tool_call({tc.name})"
    elif env.action_result.raw_response:
        status = env.action_result.raw_response.get("status", "")
        detail["headline"] = str(status)
    elif env.action_result.completion:
        detail["headline"] = env.action_result.completion[:72]
    else:
        detail["headline"] = env.boundary_kind
    return detail


def render_trace_html(graph: ExecutionGraph, *, title: str | None = None) -> str:
    """Render a self-contained HTML page for the execution graph."""
    nodes = [_envelope_summary(env) for env in graph.timeline()]
    nodes_json = json.dumps(nodes)
    mermaid = graph.to_mermaid()
    mermaid_clicks = [
        f'    click {n["short_id"]} selectByShortId "{n["boundary_id"]}@{n["invocation_index"]}"'
        for n in nodes
    ]
    page_title = title or f"Chronicle — {graph.trace_id}"
    trace_id = graph.trace_id

    mermaid_classes = [
        "    classDef llm fill:#1e3a5f,stroke:#3b82f6,color:#e8ecf4",
        "    classDef tool fill:#3d2e14,stroke:#f59e0b,color:#e8ecf4",
        "    classDef custom fill:#2a1f4a,stroke:#8b5cf6,color:#e8ecf4",
    ]
    for n in nodes:
        kind = n["boundary_kind"] if n["boundary_kind"] in _KIND_COLORS else "custom"
        mermaid_classes.append(f"    class {n['short_id']} {kind}")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{page_title}</title>
  <style>
    :root {{
      --bg: #0f1117;
      --panel: #171b26;
      --border: #2a3142;
      --text: #e8ecf4;
      --muted: #9aa3b5;
      --accent: #60a5fa;
      --llm: #3b82f6;
      --tool: #f59e0b;
      --custom: #8b5cf6;
      --danger: #ef4444;
      --ok: #22c55e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }}
    header {{
      padding: 1rem 1.5rem;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(180deg, #141925, var(--bg));
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
    }}
    header h1 {{
      margin: 0;
      font-size: 1.1rem;
      font-weight: 600;
      letter-spacing: -0.02em;
    }}
    header .trace-id {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      color: var(--muted);
      font-size: 0.85rem;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 300px 1fr;
      grid-template-rows: 1fr auto;
      height: calc(100vh - 57px);
    }}
    .timeline {{
      border-right: 1px solid var(--border);
      overflow-y: auto;
      padding: 0.75rem;
      background: var(--panel);
    }}
    .timeline h2 {{
      margin: 0 0 0.75rem;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    .step {{
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 0.75rem;
      margin-bottom: 0.5rem;
      cursor: pointer;
      background: #121622;
      transition: border-color 0.15s, transform 0.1s;
    }}
    .step:hover {{ border-color: var(--accent); }}
    .step.active {{
      border-color: var(--accent);
      box-shadow: 0 0 0 1px rgba(96,165,250,0.25);
    }}
    .step .seq {{
      font-size: 0.7rem;
      color: var(--muted);
      font-family: ui-monospace, monospace;
    }}
    .step .name {{
      font-weight: 600;
      margin: 0.2rem 0;
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }}
    .badge {{
      font-size: 0.65rem;
      padding: 0.1rem 0.4rem;
      border-radius: 999px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-weight: 700;
    }}
    .badge.llm {{ background: rgba(59,130,246,0.2); color: #93c5fd; }}
    .badge.tool {{ background: rgba(245,158,11,0.2); color: #fcd34d; }}
    .badge.custom {{ background: rgba(139,92,246,0.2); color: #c4b5fd; }}
    .step .headline {{
      font-size: 0.8rem;
      color: var(--muted);
      line-height: 1.35;
      word-break: break-word;
    }}
    .graph-panel {{
      overflow: auto;
      padding: 1rem;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      background:
        radial-gradient(circle at 20% 20%, rgba(59,130,246,0.05), transparent 40%),
        radial-gradient(circle at 80% 60%, rgba(245,158,11,0.04), transparent 35%),
        var(--bg);
    }}
    .mermaid-wrap {{
      min-width: min(100%, 720px);
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.25rem;
    }}
    .detail {{
      grid-column: 1 / -1;
      border-top: 1px solid var(--border);
      background: #121622;
      padding: 0;
      max-height: 42vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    .detail-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.75rem 1.25rem;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }}
    .detail-header h2 {{
      margin: 0;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
    }}
    .tabs {{
      display: flex;
      gap: 0.35rem;
    }}
    .tab {{
      background: transparent;
      border: 1px solid var(--border);
      color: var(--muted);
      border-radius: 6px;
      padding: 0.3rem 0.65rem;
      font-size: 0.75rem;
      cursor: pointer;
    }}
    .tab.active {{
      background: rgba(96,165,250,0.12);
      border-color: var(--accent);
      color: var(--text);
    }}
    .detail-body {{
      overflow: auto;
      padding: 1rem 1.25rem 1.25rem;
      flex: 1;
    }}
    .detail-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 0.75rem;
    }}
    .envelope-full {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.75rem;
    }}
    .envelope-full pre {{
      font-size: 0.76rem;
      max-height: none;
    }}
    .copy-btn {{
      background: #1e293b;
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 6px;
      padding: 0.3rem 0.65rem;
      font-size: 0.75rem;
      cursor: pointer;
    }}
    .copy-btn:hover {{ border-color: var(--accent); }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.75rem;
    }}
    .card h3 {{
      margin: 0 0 0.4rem;
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.78rem;
      line-height: 1.45;
      color: #d6deee;
    }}
    .status-deleted {{ color: var(--danger); }}
    .status-blocked {{ color: var(--ok); }}
  </style>
</head>
<body>
  <header>
    <h1>Chronicle Execution Graph</h1>
    <div class="trace-id">{trace_id}</div>
  </header>
  <div class="layout">
    <aside class="timeline">
      <h2>Timeline</h2>
      <div id="timeline-list"></div>
    </aside>
    <main class="graph-panel">
      <div class="mermaid-wrap">
        <pre class="mermaid">
{mermaid}
{chr(10).join(mermaid_classes)}
{chr(10).join(mermaid_clicks)}
        </pre>
      </div>
    </main>
    <section class="detail">
      <div class="detail-header">
        <h2 id="detail-title">Envelope</h2>
        <div class="tabs">
          <button class="tab active" data-tab="full">Full envelope</button>
          <button class="tab" data-tab="overview">Overview</button>
          <button class="copy-btn" id="copy-envelope" type="button">Copy JSON</button>
        </div>
      </div>
      <div class="detail-body">
        <div id="detail-panel"></div>
      </div>
    </section>
  </div>
  <script type="module">
    import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
    mermaid.initialize({{
      startOnLoad: true,
      theme: "dark",
      themeVariables: {{
        primaryColor: "#1e293b",
        primaryTextColor: "#e8ecf4",
        primaryBorderColor: "#3b82f6",
        lineColor: "#64748b",
        secondaryColor: "#172033",
        tertiaryColor: "#0f1117",
      }},
      flowchart: {{ curve: "basis", padding: 16 }},
    }});
  </script>
  <script>
    const NODES = {nodes_json};
    let activeTab = "full";
    let activeIdx = 0;

    function esc(s) {{
      return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    }}

    function renderOverview(node) {{
      let resultClass = "";
      if (node.raw_response?.status === "deleted") resultClass = "status-deleted";
      if (node.raw_response?.status === "blocked") resultClass = "status-blocked";

      return `
        <div class="detail-grid">
          <div class="card">
            <h3>Boundary</h3>
            <pre>${{esc(node.boundary_id)}}@${{node.invocation_index}} (${{esc(node.boundary_kind)}})
envelope: ${{esc(node.envelope_id)}}
parent:   ${{esc(node.parent_envelope_id || "—")}}</pre>
          </div>
          <div class="card">
            <h3>Input</h3>
            <pre>${{esc(JSON.stringify(node.graph_state, null, 2) || JSON.stringify(node.messages, null, 2))}}</pre>
          </div>
          <div class="card">
            <h3>Output</h3>
            <pre class="${{resultClass}}">${{esc(
              node.raw_response
                ? JSON.stringify(node.raw_response, null, 2)
                : node.tool_calls?.length
                  ? JSON.stringify(node.tool_calls, null, 2)
                  : node.completion || "—"
            )}}</pre>
          </div>
          <div class="card">
            <h3>Metadata</h3>
            <pre>model: ${{esc(node.model_version)}}
build: ${{esc(node.build_id)}}
finish: ${{esc(node.finish_reason || "—")}}</pre>
          </div>
        </div>
      `;
    }}

    function renderFullEnvelope(node) {{
      return `
        <div class="envelope-full">
          <pre>${{esc(JSON.stringify(node.full_envelope, null, 2))}}</pre>
        </div>
      `;
    }}

    function renderDetail(node) {{
      const panel = document.getElementById("detail-panel");
      const title = document.getElementById("detail-title");
      if (!node) {{
        panel.innerHTML = "<p style='color:#9aa3b5'>Select a step</p>";
        title.textContent = "Envelope";
        return;
      }}
      title.textContent = `${{node.boundary_id}}@${{node.invocation_index}} — envelope`;
      panel.innerHTML = activeTab === "full"
        ? renderFullEnvelope(node)
        : renderOverview(node);
    }}

    function selectNode(idx) {{
      activeIdx = idx;
      document.querySelectorAll(".step").forEach((el, i) => {{
        el.classList.toggle("active", i === idx);
      }});
      renderDetail(NODES[idx]);
    }}

    window.selectByShortId = function(shortId) {{
      const idx = NODES.findIndex(n => n.short_id === shortId || n.envelope_id.startsWith(shortId));
      if (idx >= 0) selectNode(idx);
    }};

    document.querySelectorAll(".tab").forEach(btn => {{
      btn.addEventListener("click", () => {{
        document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        activeTab = btn.dataset.tab;
        renderDetail(NODES[activeIdx]);
      }});
    }});

    document.getElementById("copy-envelope").addEventListener("click", () => {{
      const node = NODES[activeIdx];
      if (!node) return;
      navigator.clipboard.writeText(JSON.stringify(node.full_envelope, null, 2));
      const btn = document.getElementById("copy-envelope");
      const prev = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => {{ btn.textContent = prev; }}, 1200);
    }});

    const list = document.getElementById("timeline-list");
    NODES.forEach((node, idx) => {{
      const el = document.createElement("div");
      el.className = "step";
      el.innerHTML = `
        <div class="seq">#${{node.sequence}}</div>
        <div class="name">
          ${{esc(node.boundary_id)}}@${{node.invocation_index}}
          <span class="badge ${{esc(node.boundary_kind)}}">${{esc(node.boundary_kind)}}</span>
        </div>
        <div class="headline">${{esc(node.headline)}}</div>
      `;
      el.addEventListener("click", () => selectNode(idx));
      list.appendChild(el);
    }});

    if (NODES.length) selectNode(0);
  </script>
</body>
</html>
"""


def write_trace_html(graph: ExecutionGraph, path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_trace_html(graph), encoding="utf-8")
    return dest


def serve_trace_ui(
    trace_dir: str | Path,
    *,
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Start a local server rendering the trace visualization UI."""
    graph = ExecutionGraph.load(trace_dir)
    page = render_trace_html(graph).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):  # noqa: A002
            return

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Chronicle trace UI: {url}")
    print(f"Trace: {graph.trace_id}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def open_trace_ui(
    trace_dir: str | Path,
    *,
    port: int = 8765,
    open_browser: bool = True,
    write_html: str | Path | None = None,
) -> Path | None:
    """
    Open the trace UI. If write_html is set, also save a static HTML file.

    Returns the written HTML path when write_html is provided.
    """
    graph = ExecutionGraph.load(trace_dir)
    written: Path | None = None
    if write_html is not None:
        written = write_trace_html(graph, write_html)
        print(f"Wrote {written}")

    if open_browser:
        # Serve in a way that doesn't block if we're just opening - use serve in thread?
        # For show_trace --ui, blocking serve is fine
        serve_trace_ui(trace_dir, port=port, open_browser=True)
    return written
