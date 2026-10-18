import { Outlet } from "react-router-dom";
import { RibbonBackground } from "../components/bg";
import styles from "./Layout.module.css";

export default function Layout() {
  return (
    <>
      <RibbonBackground />
      <div className={styles.content}>
        <Outlet />
      </div>
    </>
  );
}
