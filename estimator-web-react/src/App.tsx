import { Route, Routes } from "react-router-dom";
import { NotFoundPage } from "./components/ErrorPage";
import { Layout } from "./components/Layout";
import { ConversationProvider, useConversation } from "./hooks/useConversation";
import { PrimaryModelProvider } from "./hooks/usePrimaryModel";
import { ChunkingHistoryPage } from "./pages/ChunkingHistoryPage";
import { ChunkingLabPage } from "./pages/ChunkingLabPage";
import { ChunkingResultPage } from "./pages/ChunkingResultPage";
import { EstimationPage } from "./pages/EstimationPage";
import { HistoryPage } from "./pages/HistoryPage";
import { NewEstimationPage } from "./pages/NewEstimationPage";
import { SettingsPage } from "./pages/SettingsPage";

/** «Nueva conversación» cambia la clave y el formulario vuelve a empezar vacío. */
function NewEstimationRoute() {
  const { resetKey } = useConversation();
  return <NewEstimationPage key={resetKey} />;
}

export function App() {
  return (
    <PrimaryModelProvider>
      <ConversationProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<NewEstimationRoute />} />
            <Route path="/estimations" element={<HistoryPage />} />
            <Route path="/estimations/:id" element={<EstimationPage />} />
            <Route path="/rag/chunking_comparisons" element={<ChunkingHistoryPage />} />
            <Route path="/rag/chunking_comparisons/new" element={<ChunkingLabPage />} />
            <Route path="/rag/chunking_comparisons/:id" element={<ChunkingResultPage />} />
            <Route path="/ai_settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </ConversationProvider>
    </PrimaryModelProvider>
  );
}
