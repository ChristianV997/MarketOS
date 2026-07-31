import { useState } from "react";
import { useUnitEconomics, useEcommerceOperator } from "@/lib/api";
import { cn } from "@/lib/utils";

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("bg-[#111113] border border-white/[0.07] rounded-xl p-4", className)}>{children}</div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-[11px] text-zinc-500 uppercase tracking-widest">{label}</span>
      {children}
    </label>
  );
}

const inputCls = "w-full bg-[#0a0a0b] border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-indigo-500/50";

function ResultPanel({ result }: { result: unknown }) {
  if (result == null) return null;
  return (
    <pre className="mt-3 bg-black/40 border border-white/[0.06] rounded-lg p-3 text-[11px] text-zinc-300 overflow-x-auto max-h-96">
      {JSON.stringify(result, null, 2)}
    </pre>
  );
}

function UnitEconomicsForm() {
  const [product, setProduct] = useState("Widget");
  const [cost, setCost] = useState(10);
  const [price, setPrice] = useState(40);
  const mutation = useUnitEconomics();

  return (
    <Card>
      <p className="text-sm font-semibold text-zinc-200 mb-3">Unit Economics</p>
      <div className="grid grid-cols-3 gap-3">
        <Field label="Product">
          <input className={inputCls} value={product} onChange={(e) => setProduct(e.target.value)} />
        </Field>
        <Field label="Cost">
          <input className={inputCls} type="number" value={cost} onChange={(e) => setCost(Number(e.target.value))} />
        </Field>
        <Field label="Price">
          <input className={inputCls} type="number" value={price} onChange={(e) => setPrice(Number(e.target.value))} />
        </Field>
      </div>
      <button
        onClick={() => mutation.mutate({ product, cost, price })}
        disabled={mutation.isPending}
        className="mt-3 px-3 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50"
      >
        {mutation.isPending ? "Running…" : "Run diagnostic"}
      </button>
      {mutation.isError && <p className="text-xs text-red-400 mt-2">{(mutation.error as Error).message}</p>}
      <ResultPanel result={mutation.data} />
    </Card>
  );
}

function EcommerceOperatorForm() {
  const [product, setProduct] = useState("Widget");
  const [roas, setRoas] = useState(2.0);
  const mutation = useEcommerceOperator();

  return (
    <Card>
      <p className="text-sm font-semibold text-zinc-200 mb-3">E-commerce Operator</p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Product">
          <input className={inputCls} value={product} onChange={(e) => setProduct(e.target.value)} />
        </Field>
        <Field label="ROAS">
          <input className={inputCls} type="number" step="0.1" value={roas} onChange={(e) => setRoas(Number(e.target.value))} />
        </Field>
      </div>
      <button
        onClick={() => mutation.mutate({ product, roas })}
        disabled={mutation.isPending}
        className="mt-3 px-3 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50"
      >
        {mutation.isPending ? "Running…" : "Evaluate readiness + decision"}
      </button>
      {mutation.isError && <p className="text-xs text-red-400 mt-2">{(mutation.error as Error).message}</p>}
      <ResultPanel result={mutation.data} />
    </Card>
  );
}

export default function Services() {
  return (
    <div className="max-w-3xl mx-auto p-6 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Services</h1>
        <p className="text-xs text-zinc-500 mt-0.5">
          Run a MarketOS service module directly against api/routes/services.py.
        </p>
      </div>
      <UnitEconomicsForm />
      <EcommerceOperatorForm />
    </div>
  );
}
