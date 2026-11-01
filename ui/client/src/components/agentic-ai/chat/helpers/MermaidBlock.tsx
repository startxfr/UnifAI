import { useEffect, useRef, useState } from "react";

let mermaidReady: Promise<typeof import("mermaid").default> | null = null;
let counter = 0;

// Loaded on first use (own chunk), so a chat without a diagram never downloads it.
function loadMermaid() {
  if (!mermaidReady) {
    mermaidReady = import("mermaid").then(({ default: mermaid }) => {
      // "strict": labels are sanitised, no click callbacks, no HTML in nodes.
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "dark", suppressErrorRendering: true });
      return mermaid;
    });
  }
  return mermaidReady;
}

/** A ```mermaid block drawn as a diagram; the plain code block while it renders, and when the source does not parse. */
export function MermaidBlock({ source }: { source: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    const el = host.current;
    const render = () => {
      const id = `mermaid-${++counter}`;
      return loadMermaid()
        .then((mermaid) => mermaid.render(id, source))
        .then((out) => !cancelled && setSvg(out.svg))
        .catch(() => {
          // mermaid leaves its error graphic (and a work element) in <body> when the source does not parse.
          document.getElementById(id)?.remove();
          document.getElementById(`d${id}`)?.remove();
          if (!cancelled) setSvg(null);
        });
    };
    // Lazy: only when the block scrolls into view.
    if (el && typeof IntersectionObserver !== "undefined") {
      const io = new IntersectionObserver((entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          io.disconnect();
          render();
        }
      });
      io.observe(el);
      return () => {
        cancelled = true;
        io.disconnect();
      };
    }
    render();
    return () => {
      cancelled = true;
    };
  }, [source]);

  if (svg) {
    return (
      <div
        className="bg-gray-900 p-3 rounded-lg overflow-x-auto mb-3 mt-2 flex justify-center"
        data-testid="mermaid-diagram"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    );
  }
  return (
    <div ref={host}>
      <pre className="bg-gray-900 text-cyan-300 p-3 rounded-lg overflow-x-auto mb-3 mt-2 whitespace-pre">
        <code className="font-mono text-sm">{source}</code>
      </pre>
    </div>
  );
}
