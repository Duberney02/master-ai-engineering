import { Route, Routes } from "react-router-dom";
import { NotFoundPage } from "./components/ErrorPage";
import { Layout } from "./components/Layout";
import { ConversationProvider, useConversation } from "./hooks/useConversation";
import { EstimationPage } from "./pages/EstimationPage";
import { HistoryPage } from "./pages/HistoryPage";
import { NewEstimationPage } from "./pages/NewEstimationPage";

/** «Nueva conversación» cambia la clave y el formulario vuelve a empezar vacío. */
function NewEstimationRoute() {
  const { resetKey } = useConversation();
  return <NewEstimationPage key={resetKey} />;
}

export function App() {
  return (
    <ConversationProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<NewEstimationRoute />} />
          <Route path="/estimations" element={<HistoryPage />} />
          <Route path="/estimations/:id" element={<EstimationPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </ConversationProvider>
  );
}
