import { Route, Routes } from "react-router-dom";
import { NotFoundPage } from "./components/ErrorPage";
import { Layout } from "./components/Layout";
import { EstimationPage } from "./pages/EstimationPage";
import { HistoryPage } from "./pages/HistoryPage";
import { NewEstimationPage } from "./pages/NewEstimationPage";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<NewEstimationPage />} />
        <Route path="/estimations" element={<HistoryPage />} />
        <Route path="/estimations/:id" element={<EstimationPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
