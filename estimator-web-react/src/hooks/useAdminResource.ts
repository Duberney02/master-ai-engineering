import { useCallback, useEffect, useState } from "react";
import { EstimatorApiError } from "../api/estimatorApi";
import { useShell } from "./useShell";

export type AdminResource<T> =
  | { status: "loading" }
  | { status: "denied" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

export const GENERIC_FAILURE = "No se pudo completar la operación.";

export function messageOf(error: unknown): string {
  return error instanceof EstimatorApiError ? error.message : GENERIC_FAILURE;
}

/**
 * Carga un recurso administrativo. Distingue el acceso restringido (403 de Go, sin datos) de un fallo del servicio y
 * permite reintentar. Informa del acceso a la cabecera.
 */
export function useAdminResource<T>(load: (signal: AbortSignal) => Promise<T>, key = ""): AdminResource<T> & { reload: () => void } {
  const { reportAccess } = useShell();
  const [state, setState] = useState<AdminResource<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    load(controller.signal)
      .then((data) => {
        reportAccess("allowed");
        setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof EstimatorApiError && error.status === 403) {
          reportAccess("denied");
          setState({ status: "denied" });
        } else {
          setState({ status: "error", message: messageOf(error) });
        }
      });
    return () => controller.abort();
    // `load` se recrea en cada render: la carga depende de `key` y de los reintentos.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt, key, reportAccess]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  return { ...state, reload };
}
