import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Info,
  Loader2,
  Upload,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { qk } from "@/lib/queryKeys";
import { SUPPORTED_CURRENCIES, type Currency } from "@/lib/constants";
import { useCurrency } from "@/hooks/useCurrency";
import { parseApiError } from "@/api/client";
import * as txApi from "@/api/transactions.api";
import { cn } from "@/lib/utils";

type Step = "upload" | "map" | "done";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}

export function CsvImportDialog({ open, onOpenChange }: Props) {
  const baseCurrency = useCurrency();
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<txApi.ImportPreviewResult | null>(null);
  const [mapping, setMapping] = useState<txApi.ImportMapping | null>(null);
  const [committed, setCommitted] = useState<txApi.ImportCommitResult | null>(null);

  // Reset everything whenever the dialog closes.
  useEffect(() => {
    if (!open) {
      setStep("upload");
      setFile(null);
      setPreview(null);
      setMapping(null);
      setCommitted(null);
    }
  }, [open]);

  const previewMutation = useMutation({
    mutationFn: (f: File) => txApi.previewCsv(f),
    onSuccess: (result) => {
      setPreview(result);
      setMapping({
        date: result.suggested_mapping.date ?? "",
        description: result.suggested_mapping.description ?? "",
        amount: result.suggested_mapping.amount ?? undefined,
        debit: result.suggested_mapping.debit ?? undefined,
        credit: result.suggested_mapping.credit ?? undefined,
        currency: result.suggested_mapping.currency ?? undefined,
        merchant: result.suggested_mapping.merchant ?? undefined,
        default_currency: baseCurrency,
      });
      setStep("map");
    },
  });

  const commitMutation = useMutation({
    mutationFn: (args: { file: File; mapping: txApi.ImportMapping }) =>
      txApi.commitCsvImport(args.file, args.mapping),
    onSuccess: (result) => {
      setCommitted(result);
      setStep("done");
      qc.invalidateQueries({ queryKey: qk.transactions.all() });
      qc.invalidateQueries({ queryKey: qk.reports.all() });
      qc.invalidateQueries({ queryKey: qk.accounts.all() });
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Import transactions from CSV</DialogTitle>
          <DialogDescription>
            Works with most Romanian banks (BCR, ING, Revolut, BT, Raiffeisen). Both
            comma- and semicolon-delimited files, English and Romanian column names.
          </DialogDescription>
        </DialogHeader>

        <Stepper current={step} />

        {step === "upload" && (
          <UploadStep
            file={file}
            setFile={setFile}
            error={previewMutation.error}
            isLoading={previewMutation.isPending}
          />
        )}

        {step === "map" && preview && mapping && (
          <MapStep preview={preview} mapping={mapping} setMapping={setMapping} />
        )}

        {step === "done" && committed && (
          <DoneStep committed={committed} onClose={() => onOpenChange(false)} />
        )}

        <DialogFooter>
          {step === "upload" && (
            <>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                disabled={!file || previewMutation.isPending}
                onClick={() => file && previewMutation.mutate(file)}
              >
                {previewMutation.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Reading…
                  </>
                ) : (
                  <>
                    Continue <Upload className="h-4 w-4" />
                  </>
                )}
              </Button>
            </>
          )}

          {step === "map" && (
            <>
              <Button variant="ghost" onClick={() => setStep("upload")} disabled={commitMutation.isPending}>
                Back
              </Button>
              <Button
                variant="primary"
                disabled={
                  commitMutation.isPending ||
                  !mapping?.date ||
                  !mapping?.description ||
                  !(mapping.amount || (mapping.debit && mapping.credit))
                }
                onClick={() => {
                  if (file && mapping) commitMutation.mutate({ file, mapping });
                }}
              >
                {commitMutation.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Importing…
                  </>
                ) : (
                  "Import all rows"
                )}
              </Button>
            </>
          )}

          {step === "done" && (
            <Button variant="primary" onClick={() => onOpenChange(false)}>
              Done
            </Button>
          )}
        </DialogFooter>

        {commitMutation.isError && step === "map" && (
          <div role="alert" className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-body-small text-danger">
            {parseApiError(commitMutation.error)}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/* ------------------------------ Stepper ------------------------------ */

function Stepper({ current }: { current: Step }) {
  const steps: { id: Step; label: string }[] = [
    { id: "upload", label: "Upload" },
    { id: "map", label: "Map columns" },
    { id: "done", label: "Confirm" },
  ];
  const activeIndex = steps.findIndex((s) => s.id === current);
  return (
    <ol className="flex items-center gap-2 text-uppercase-label uppercase text-text-muted">
      {steps.map((s, i) => {
        const state = i < activeIndex ? "done" : i === activeIndex ? "active" : "todo";
        return (
          <li key={s.id} className="flex items-center gap-2">
            <span
              className={cn(
                "flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold",
                state === "active" && "bg-primary text-on-primary",
                state === "done" && "bg-success text-white",
                state === "todo" && "bg-surface-variant text-text-muted",
              )}
            >
              {state === "done" ? <CheckCircle2 className="h-3.5 w-3.5" /> : i + 1}
            </span>
            <span className={cn(state === "active" && "text-text-primary")}>{s.label}</span>
            {i < steps.length - 1 && <span className="text-text-muted">→</span>}
          </li>
        );
      })}
    </ol>
  );
}

/* ------------------------------ Upload step ------------------------------ */

/** Sample CSV the user can download to see the shape we expect. Comma-delimited
 *  with a single signed `Amount` column; works as-is with the auto-mapping. */
const SAMPLE_CSV = `Date,Description,Amount,Currency,Merchant
2026-05-04,GLOVO order,-65.00,RON,Glovo
2026-05-04,CARREFOUR Baneasa,-342.50,RON,Carrefour
2026-05-03,SALARIU ACME SRL,3800.00,RON,Acme SRL
2026-05-03,STB Abonament,-75.00,RON,STB
2026-05-02,SPOTIFY*PREMIUM,-35.00,RON,Spotify
2026-05-02,Vodafone factura,-49.00,RON,Vodafone
2026-05-01,CHIRIE Aviatorilor,-3200.00,RON,Owner
`;

function downloadSample() {
  const blob = new Blob([SAMPLE_CSV], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "lumen-import-template.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function UploadStep({
  file,
  setFile,
  error,
  isLoading,
}: {
  file: File | null;
  setFile: (f: File | null) => void;
  error: unknown;
  isLoading: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const f = files[0];
    if (!/\.csv$/i.test(f.name)) {
      alert("Please choose a .csv file.");
      return;
    }
    setFile(f);
  };

  return (
    <div className="space-y-md">
      {/* Format help — visible *before* picking a file so users know what to bring. */}
      <div className="flex items-start gap-3 rounded-xl border border-primary/20 bg-primary-tint/40 p-md">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <div className="flex-1 space-y-2 text-body-small">
          <p className="text-text-primary">
            <strong>Most Romanian bank exports work as-is.</strong> We auto-detect the delimiter
            (comma or semicolon) and try to map columns by their name.
          </p>
          <details className="text-text-muted">
            <summary className="cursor-pointer font-medium text-text-primary hover:text-primary">
              What columns do you look for?
            </summary>
            <div className="mt-2 grid grid-cols-1 gap-x-md gap-y-1 sm:grid-cols-2">
              <div>
                <span className="font-medium text-text-primary">Date</span>
                <span className="text-text-muted">
                  {" "}— "Date", "Data", "Booking date", "Value date"
                </span>
              </div>
              <div>
                <span className="font-medium text-text-primary">Description</span>
                <span className="text-text-muted">
                  {" "}— "Description", "Descriere", "Details", "Explicatii"
                </span>
              </div>
              <div>
                <span className="font-medium text-text-primary">Amount</span>
                <span className="text-text-muted">
                  {" "}— either one signed "Amount" / "Suma" column…
                </span>
              </div>
              <div>
                <span className="font-medium text-text-primary">…or split</span>
                <span className="text-text-muted">
                  {" "}— "Debit" + "Credit" columns (BCR-style)
                </span>
              </div>
              <div>
                <span className="font-medium text-text-primary">Currency</span>
                <span className="text-text-muted">
                  {" "}— "Currency", "Moneda", "Valuta" (optional)
                </span>
              </div>
              <div>
                <span className="font-medium text-text-primary">Merchant</span>
                <span className="text-text-muted">
                  {" "}— "Merchant", "Comerciant", "Beneficiar" (optional)
                </span>
              </div>
            </div>
          </details>
          <button
            type="button"
            onClick={downloadSample}
            className="inline-flex items-center gap-1.5 text-body-small font-medium text-primary hover:underline focus-ring rounded"
          >
            <Download className="h-3.5 w-3.5" /> Download a sample template
          </button>
        </div>
      </div>

      {file ? (
        <div className="flex items-center gap-3 rounded-xl border border-border bg-surface-soft p-md">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-tint text-primary">
            <FileSpreadsheet className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-body-small font-semibold">{file.name}</div>
            <div className="text-uppercase-label uppercase text-text-muted">
              {(file.size / 1024).toFixed(1)} KB
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Remove file"
            onClick={() => {
              setFile(null);
              if (inputRef.current) inputRef.current.value = "";
            }}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      ) : (
        <label
          htmlFor="csv-file-input"
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            handleFiles(e.dataTransfer.files);
          }}
          className={cn(
            "flex h-44 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed bg-surface-soft text-center transition-colors",
            dragOver ? "border-primary bg-primary-tint/40" : "border-border hover:border-outline",
          )}
        >
          <Upload className="h-8 w-8 text-text-muted" />
          <p className="text-body-small font-medium text-text-primary">Drop your CSV here</p>
          <p className="text-uppercase-label uppercase text-text-muted">or click to choose a file</p>
        </label>
      )}

      <input
        id="csv-file-input"
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        className="sr-only"
        onChange={(e) => handleFiles(e.target.files)}
      />

      {error ? (
        <div role="alert" className="rounded-lg border border-danger/30 bg-danger/10 p-3 text-body-small text-danger">
          {parseApiError(error)}
        </div>
      ) : null}

      {isLoading && (
        <p className="text-uppercase-label uppercase text-text-muted">
          Sniffing delimiter and column shape…
        </p>
      )}
    </div>
  );
}

/* ------------------------------ Map step ------------------------------ */

function MapStep({
  preview,
  mapping,
  setMapping,
}: {
  preview: txApi.ImportPreviewResult;
  mapping: txApi.ImportMapping;
  setMapping: (m: txApi.ImportMapping) => void;
}) {
  const setField = <K extends keyof txApi.ImportMapping>(k: K, v: txApi.ImportMapping[K]) =>
    setMapping({ ...mapping, [k]: v });

  const useDebitCredit = !!mapping.debit || !!mapping.credit;

  const Pick = ({
    label,
    value,
    onChange,
    optional,
  }: {
    label: string;
    value: string | undefined;
    onChange: (v: string | undefined) => void;
    optional?: boolean;
  }) => (
    <div className="space-y-1">
      <label className="text-uppercase-label uppercase text-text-muted">
        {label}
        {optional && <span className="ml-1 normal-case text-text-muted/60">(optional)</span>}
      </label>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || undefined)}
        className="flex h-9 w-full rounded-lg border border-border bg-surface px-2 text-body-small focus-ring"
      >
        <option value="">— none —</option>
        {preview.headers.map((h) => (
          <option key={h} value={h}>
            {h}
          </option>
        ))}
      </select>
    </div>
  );

  return (
    <div className="space-y-md">
      <div className="rounded-lg border border-border bg-surface-soft p-3 text-body-small text-text-muted">
        Detected <strong className="text-text-primary">{preview.total_rows} rows</strong> with{" "}
        <strong className="text-text-primary">"{preview.delimiter}"</strong> delimiter. Confirm
        the column mapping below — we suggest a starting point based on common Romanian and
        English bank exports.
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Pick label="Date" value={mapping.date} onChange={(v) => setField("date", v ?? "")} />
        <Pick
          label="Description"
          value={mapping.description}
          onChange={(v) => setField("description", v ?? "")}
        />
      </div>

      <div className="rounded-lg border border-border p-3">
        <div className="mb-2 flex items-center gap-3 text-body-small">
          <strong>Amount mapping</strong>
          <span className="text-text-muted">— pick one of two patterns:</span>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {!useDebitCredit ? (
            <Pick label="Single signed amount column" value={mapping.amount} onChange={(v) => setField("amount", v)} />
          ) : (
            <div />
          )}
          {useDebitCredit && (
            <>
              <Pick label="Debit (expense)" value={mapping.debit} onChange={(v) => setField("debit", v)} />
              <Pick label="Credit (income)" value={mapping.credit} onChange={(v) => setField("credit", v)} />
            </>
          )}
        </div>
        <button
          type="button"
          className="mt-2 text-body-small font-medium text-primary hover:underline focus-ring rounded"
          onClick={() => {
            if (useDebitCredit) {
              setMapping({ ...mapping, debit: undefined, credit: undefined, amount: mapping.amount ?? undefined });
            } else {
              setMapping({ ...mapping, amount: undefined, debit: "", credit: "" });
            }
          }}
        >
          {useDebitCredit ? "Switch to single amount column" : "Switch to split debit/credit"}
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Pick
          label="Currency"
          value={mapping.currency}
          onChange={(v) => setField("currency", v)}
          optional
        />
        <Pick
          label="Merchant"
          value={mapping.merchant}
          onChange={(v) => setField("merchant", v)}
          optional
        />
      </div>

      <div className="space-y-1">
        <label className="text-uppercase-label uppercase text-text-muted">
          Default currency (when row has no currency column)
        </label>
        <select
          value={mapping.default_currency}
          onChange={(e) => setField("default_currency", e.target.value as Currency)}
          className="flex h-9 w-32 rounded-lg border border-border bg-surface px-2 text-body-small focus-ring"
        >
          {SUPPORTED_CURRENCIES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </div>

      {/* Sample preview */}
      <details className="rounded-lg border border-border">
        <summary className="cursor-pointer p-3 text-body-small font-medium">
          Preview of first 5 rows
        </summary>
        <div className="overflow-x-auto border-t border-border">
          <table className="w-full text-body-small">
            <thead className="bg-surface-soft text-uppercase-label uppercase text-text-muted">
              <tr>
                {preview.headers.map((h) => (
                  <th key={h} className="px-3 py-2 text-left font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.sample_rows.map((r, i) => (
                <tr key={i} className="border-t border-border/60">
                  {preview.headers.map((h) => (
                    <td key={h} className="px-3 py-2 text-text-muted">
                      {String(r[h] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

/* ------------------------------ Done step ------------------------------ */

function DoneStep({
  committed,
  onClose,
}: {
  committed: txApi.ImportCommitResult;
  onClose: () => void;
}) {
  return (
    <div className="space-y-md">
      <div className="flex items-center gap-3 rounded-xl border border-success/30 bg-success/10 p-md">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-success text-white">
          <CheckCircle2 className="h-5 w-5" />
        </div>
        <div>
          <div className="font-semibold text-text-primary">
            {committed.inserted} transaction{committed.inserted === 1 ? "" : "s"} imported
          </div>
          <div className="text-body-small text-text-muted">
            Each row was auto-categorized using the rules engine. You can recategorize
            anything from the list view.
          </div>
        </div>
      </div>

      {committed.skipped > 0 && (
        <div className="flex items-start gap-3 rounded-xl border border-warning/30 bg-warning/10 p-md">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-warning-700" />
          <div className="flex-1">
            <div className="font-medium text-text-primary">
              {committed.skipped} row{committed.skipped === 1 ? "" : "s"} skipped
            </div>
            {committed.errors.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-body-small text-text-muted">
                {committed.errors.slice(0, 5).map((e, i) => (
                  <li key={i} className="font-mono">
                    {e}
                  </li>
                ))}
                {committed.errors.length > 5 && (
                  <li className="text-uppercase-label uppercase">
                    + {committed.errors.length - 5} more
                  </li>
                )}
              </ul>
            )}
          </div>
        </div>
      )}

      <p className="text-body-small text-text-muted">
        Tip: review the imported batch on the Transactions page and refine any miscategorized
        rows — every correction trains the cascade.
      </p>
      <Button variant="ghost" size="sm" onClick={onClose} className="hidden">
        {/* placeholder for click handler reference */}
      </Button>
    </div>
  );
}
