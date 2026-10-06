import type { ReactNode } from "react";

interface Props {
  kind: "error" | "warn";
  id?: string;
  children: ReactNode;
}

/** Aviso en línea; los errores se anuncian a lectores de pantalla con role="alert". */
export function Alert({ kind, id, children }: Props) {
  return (
    <div className={`alert ${kind}`} id={id} role={kind === "error" ? "alert" : undefined}>
      {children}
    </div>
  );
}
