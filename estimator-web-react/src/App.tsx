import { Route, Routes } from "react-router-dom";
import { NotFoundPage } from "./components/ErrorPage";
import { Layout } from "./components/Layout";
import { ConversationProvider, useConversation } from "./hooks/useConversation";
import { ShellProvider } from "./hooks/useShell";
import { EstimationPage } from "./pages/EstimationPage";
import { HistoryPage } from "./pages/HistoryPage";
import { LabDetailPage } from "./pages/LabDetailPage";
import { LabHistoryPage } from "./pages/LabHistoryPage";
import { LabNewPage } from "./pages/LabNewPage";
import { NewEstimationPage } from "./pages/NewEstimationPage";
import { SettingsPage } from "./pages/SettingsPage";

/** «Nueva conversación» cambia la clave y el formulario vuelve a empezar vacío. */
function NewEstimationRoute() {
  const { resetKey } = useConversation();
  return <NewEstimationPage key={resetKey} />;
}

export function App() {
  return (
    <ShellProvider>
    <ConversationProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<NewEstimationRoute />} />
          <Route path="/estimations" element={<HistoryPage />} />
          <Route path="/estimations/:id" element={<EstimationPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/rag/chunking-comparisons" element={<LabHistoryPage />} />
          <Route path="/rag/chunking-comparisons/new" element={<LabNewPage />} />
          <Route path="/rag/chunking-comparisons/:id" element={<LabDetailPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </ConversationProvider>
    </ShellProvider>
  );
}
