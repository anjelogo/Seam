import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Avatar from "./routes/Avatar";
import Layout from "./routes/Layout";
import LogIn from "./routes/LogIn";
import Onboarding from "./routes/Onboarding";
import SignUp from "./routes/SignUp";
import Splash from "./routes/Splash";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Splash />} />
          <Route path="signup" element={<SignUp />} />
          <Route path="login" element={<LogIn />} />
          <Route path="onboarding" element={<Onboarding />} />
          <Route path="avatar" element={<Avatar />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
