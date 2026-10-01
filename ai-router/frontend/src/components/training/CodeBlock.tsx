import { useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { IonIcon } from "@ionic/react";
import { copyOutline, checkmarkOutline } from "ionicons/icons";

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Older WebViews: fall back to a hidden textarea + execCommand.
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

/** Plain text of a React subtree — used to pull the raw code out of <pre><code>. */
function textOf(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (typeof node === "object" && "props" in node) return textOf((node as { props: { children?: ReactNode } }).props.children);
  return "";
}

/**
 * A fenced code block with its OWN "Copy code" button. The button copies
 * only the code inside this block — never the explanation around it.
 */
export function CodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    if (await copyText(code.replace(/\n$/, ""))) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    }
  }
  return (
    <div className="tr-code">
      <div className="tr-code__bar">
        <span className="tr-code__lang">{language || "code"}</span>
        <button type="button" className="tr-code__copy" onClick={copy} aria-label="Copy code">
          <IonIcon icon={copied ? checkmarkOutline : copyOutline} />
          {copied ? "Copied" : "Copy code"}
        </button>
      </div>
      <pre>
        <code>{code.replace(/\n$/, "")}</code>
      </pre>
    </div>
  );
}

/** Markdown renderer for lessons, examples and feedback. */
export function RichText({ children }: { children: string }) {
  return (
    <div className="markdown-body tr-rich">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Block code: swallow the default <pre> and render our own block.
          pre({ children: kids }) {
            const child = Array.isArray(kids) ? kids[0] : kids;
            const props = (child as { props?: { className?: string; children?: ReactNode } } | undefined)?.props ?? {};
            const lang = /language-([\w+#-]+)/.exec(props.className ?? "")?.[1];
            return <CodeBlock code={textOf(props.children)} language={lang} />;
          },
          // Inline code stays inline (no copy button for `snippets`).
          code({ children: kids, className }) {
            return <code className={className}>{kids}</code>;
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
