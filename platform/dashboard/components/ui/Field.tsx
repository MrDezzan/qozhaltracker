export function Field({
  label,
  name,
  placeholder,
  hint,
  type = "text",
  required,
  mono,
  defaultValue,
}: {
  label: string;
  name: string;
  placeholder?: string;
  hint?: string;
  type?: string;
  required?: boolean;
  mono?: boolean;
  defaultValue?: string;
}) {
  return (
    <div>
      <label htmlFor={name} className="block text-sm font-medium text-muted mb-2">
        {label}
      </label>
      <input
        id={name}
        name={name}
        type={type}
        required={required}
        placeholder={placeholder}
        defaultValue={defaultValue}
        className={`w-full border border-line rounded-lg px-3.5 py-2.5 text-sm bg-surface placeholder:text-faint transition-shadow focus:outline-none focus:ring-4 focus:ring-brand/5 focus:border-brand ${
          mono ? "font-mono text-xs" : ""
        }`}
      />
      {hint && <p className="text-sm text-faint mt-2 leading-relaxed">{hint}</p>}
    </div>
  );
}
