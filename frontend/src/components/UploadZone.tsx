import { useState } from "react";

interface Props {
  disabled: boolean;
  onFiles: (files: File[]) => void;
}

const ACCEPT = ".csv,.tsv,.xlsx";

export function UploadZone({ disabled, onFiles }: Props) {
  const [over, setOver] = useState(false);

  function take(list: FileList | null) {
    if (!list || list.length === 0) return;
    onFiles(Array.from(list));
  }

  return (
    <label
      className={[
        "block cursor-pointer border px-3 py-5 text-center transition-colors",
        over ? "border-ink bg-ticket" : "border-line bg-panel focus-within:border-ink",
        disabled ? "pointer-events-none opacity-50" : "",
      ].join(" ")}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        take(e.dataTransfer.files);
      }}
    >
      <input
        type="file"
        accept={ACCEPT}
        multiple
        className="sr-only"
        aria-label="Upload spreadsheet"
        disabled={disabled}
        onChange={(e) => {
          take(e.target.files);
          e.target.value = "";
        }}
      />
      <p className="text-[13px] font-medium text-ink">Drop a spreadsheet</p>
      <p className="mt-1 font-mono text-[11px] text-muted">CSV · TSV · XLSX</p>
    </label>
  );
}
