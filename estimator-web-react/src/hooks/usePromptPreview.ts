import { useEffect, useState } from "react";
import { promptPreview } from "../api/estimatorApi";
import type { PromptPreview } from "../api/types";

export interface PreviewOptions {
  prompt_version?: string;
  project_type?: string;
  detail_level?: string;
  output_format?: string;
}

export interface PreviewState {
  /** Prompt renderizado, o null si aún no llegó o si la API no pudo renderizarlo. */
  preview: PromptPreview | null;
  loading: boolean;
}

/**
 * Obtiene el prompt de sistema y los ejemplos para las opciones vigentes (barra lateral).
 * Cancela la petición anterior al cambiar las opciones y falla en silencio: la barra es
 * informativa y la página sigue funcionando sin ella.
 */
export function usePromptPreview(options: PreviewOptions | null): PreviewState {
  const [state, setState] = useState<PreviewState>({ preview: null, loading: options !== null });
  const version = options?.prompt_version;
  const projectType = options?.project_type;
  const detailLevel = options?.detail_level;
  const outputFormat = options?.output_format;
  const enabled = options !== null && Boolean(version);

  useEffect(() => {
    if (!enabled) {
      setState({ preview: null, loading: false });
      return;
    }
    const controller = new AbortController();
    setState((current) => ({ preview: current.preview, loading: true }));
    promptPreview(
      { prompt_version: version!, project_type: projectType, detail_level: detailLevel, output_format: outputFormat },
      controller.signal,
    )
      .then((preview) => {
        if (!controller.signal.aborted) setState({ preview, loading: false });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ preview: null, loading: false });
      });
    return () => controller.abort();
  }, [enabled, version, projectType, detailLevel, outputFormat]);

  return state;
}
