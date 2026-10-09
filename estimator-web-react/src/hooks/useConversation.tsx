// Conversación con memoria: guarda el `session_id` y los metadatos del proyecto a nivel de aplicación.
//
// La sesión se crea al cargar la página y se conserva mientras siga abierta (sobrevive a la navegación
// entre pantallas, no a una recarga: el servicio guarda las sesiones solo en memoria). «Nueva
// conversación» abre otra sesión y reinicia el estado; si la API ya no conoce la sesión, se abre otra
// y se avisa al usuario.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { SESSION_EXPIRED_MESSAGE, createSession } from "../api/estimatorApi";
import { EMPTY_METADATA, type ProjectMetadata, type SessionEstimationResponse } from "../api/types";

export interface Conversation {
  sessionId: string | null;
  metadata: ProjectMetadata;
  turnCount: number;
  /** Aviso a mostrar en el formulario (p. ej. sesión caducada). */
  notice: string | null;
  /** Cambia con cada «Nueva conversación»: las pantallas lo usan como `key` para reiniciar su estado. */
  resetKey: number;
  /** Identificador de la sesión vigente; la crea si aún no existe (por ejemplo, si falló al cargar). */
  ensureSession: () => Promise<string>;
  recordEstimation: (response: SessionEstimationResponse) => void;
  newConversation: () => Promise<void>;
  /** La API perdió la sesión: abre otra, vacía los metadatos y avisa con `notice`. */
  recoverExpired: () => Promise<void>;
}

const inactive: Conversation = {
  sessionId: null,
  metadata: EMPTY_METADATA,
  turnCount: 0,
  notice: null,
  resetKey: 0,
  ensureSession: () => Promise.reject(new Error("Sin conversación")),
  recordEstimation: () => undefined,
  newConversation: async () => undefined,
  recoverExpired: async () => undefined,
};

const ConversationContext = createContext<Conversation>(inactive);

export function useConversation(): Conversation {
  return useContext(ConversationContext);
}

export function ConversationProvider({ children }: { children: ReactNode }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<ProjectMetadata>(EMPTY_METADATA);
  const [turnCount, setTurnCount] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [resetKey, setResetKey] = useState(0);
  const current = useRef<string | null>(null);
  const pending = useRef<Promise<string> | null>(null);

  // Una sola creación en curso: el doble efecto de StrictMode o un envío rápido no abren dos sesiones.
  const open = useCallback((): Promise<string> => {
    if (!pending.current) {
      pending.current = createSession()
        .then((id) => {
          current.current = id;
          setSessionId(id);
          return id;
        })
        .finally(() => {
          pending.current = null;
        });
    }
    return pending.current;
  }, []);

  useEffect(() => {
    // Si falla aquí no se muestra nada: el siguiente envío lo reintenta con `ensureSession`.
    open().catch(() => undefined);
  }, [open]);

  const ensureSession = useCallback(() => (current.current ? Promise.resolve(current.current) : open()), [open]);

  const reset = useCallback(
    async (nextNotice: string | null, remount: boolean) => {
      current.current = null;
      setSessionId(null);
      setMetadata(EMPTY_METADATA);
      setTurnCount(0);
      setNotice(nextNotice);
      if (remount) setResetKey((key) => key + 1);
      await open().catch(() => undefined);
    },
    [open],
  );

  const value = useMemo<Conversation>(
    () => ({
      sessionId,
      metadata,
      turnCount,
      notice,
      resetKey,
      ensureSession,
      recordEstimation: (response) => {
        setMetadata(response.project_metadata);
        setTurnCount(response.turn_count);
        setNotice(null);
      },
      newConversation: () => reset(null, true),
      recoverExpired: () => reset(SESSION_EXPIRED_MESSAGE, false),
    }),
    [sessionId, metadata, turnCount, notice, resetKey, ensureSession, reset],
  );

  return <ConversationContext.Provider value={value}>{children}</ConversationContext.Provider>;
}
