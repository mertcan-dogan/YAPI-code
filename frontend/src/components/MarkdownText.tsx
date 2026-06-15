// CR-007-F / CR-008-D — lightweight, XSS-safe markdown renderer shared by the
// AI Asistan chat and the Çalışma Alanım board. Renders **bold**, headings,
// bullet lists and dividers WITHOUT dangerouslySetInnerHTML (never injects raw
// HTML from model output).
import type { JSX } from "react";

function renderInline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <span key={i}>{part}</span>
  );
}

export function renderMarkdown(text: string): JSX.Element[] {
  const lines = (text ?? "").replace(/\r/g, "").split("\n");
  const blocks: JSX.Element[] = [];
  let list: string[] = [];
  const flushList = () => {
    if (!list.length) return;
    const items = list;
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="my-1 list-disc space-y-1 pl-5">
        {items.map((li, i) => <li key={i}>{renderInline(li)}</li>)}
      </ul>
    );
    list = [];
  };
  lines.forEach((raw) => {
    const t = raw.trimEnd().trim();
    if (!t) { flushList(); return; }
    if (/^#{1,6}\s/.test(t)) {
      flushList();
      const level = t.match(/^#+/)![0].length;
      const content = t.replace(/^#+\s/, "");
      blocks.push(
        <p key={`h-${blocks.length}`} className={`font-semibold text-primary ${level <= 2 ? "mt-3 text-[15px]" : "mt-2 text-sm"} first:mt-0`}>
          {renderInline(content)}
        </p>
      );
      return;
    }
    if (/^([-*•])\s/.test(t)) { list.push(t.replace(/^([-*•])\s/, "")); return; }
    if (/^[-—_]{3,}$/.test(t)) { flushList(); blocks.push(<hr key={`hr-${blocks.length}`} className="my-3 border-border" />); return; }
    flushList();
    blocks.push(<p key={`p-${blocks.length}`} className="my-1">{renderInline(t)}</p>);
  });
  flushList();
  return blocks;
}

export function MarkdownText({ text }: { text: string }) {
  return <div className="space-y-0.5">{renderMarkdown(text)}</div>;
}
