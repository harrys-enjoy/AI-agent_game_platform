import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { VideoAgentPage } from "./video-agent/VideoAgentPage";
import "./video-agent/styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <VideoAgentPage />
  </StrictMode>,
);
