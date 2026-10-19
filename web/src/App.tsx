import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./components/RequireAuth";
import Avatar from "./routes/Avatar";
import Layout from "./routes/Layout";
import LogIn from "./routes/LogIn";
import Onboarding from "./routes/Onboarding";
import SignUp from "./routes/SignUp";
import Splash from "./routes/Splash";
import { useSession } from "./state";

export default function App() {
  useEffect(() => {
    void useSession.getState().hydrate();
  }, []);

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Splash />} />
          <Route path="signup" element={<SignUp />} />
          <Route path="login" element={<LogIn />} />
          <Route path="onboarding" element={<RequireAuth><Onboarding /></RequireAuth>} />
          <Route path="avatar" element={<RequireAuth><Avatar /></RequireAuth>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
