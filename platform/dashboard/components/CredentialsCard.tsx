"use client";
import { useState } from "react";

type Props = {
  title: string;
  hint?: string;
  text: string;
};

export function CredentialsCard({ title, hint, text }: Props) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <section className="bg-surface border border-line rounded-xl overflow-hidden">
      <header className="flex items-center justify-between gap-4 px-6 py-4">
        <div>
          <h3 className="text-sm font-medium text-ink">{title}</h3>
          {hint && <p className="text-sm text-muted mt-0.5">{hint}</p>}
        </div>
        <button
          type="button"
          onClick={copy}
          className={`shrink-0 rounded-lg border px-3.5 py-2 text-sm font-medium transition-colors ${
            copied
              ? "border-line bg-surface text-calm"
              : "border-action-hover bg-action text-on-action hover:bg-action-hover hover:text-surface"
          }`}
        >
          {copied ? "Скопировано" : "Копировать"}
        </button>
      </header>
      <pre className="text-xs font-mono bg-soft border-t border-line px-6 py-5 whitespace-pre-wrap break-all text-muted leading-relaxed">
        {text}
      </pre>
    </section>
  );
}
