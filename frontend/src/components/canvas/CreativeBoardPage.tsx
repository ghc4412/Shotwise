import { CreativeBoardWorkspace } from "./CreativeBoardWorkspace";

export function CreativeBoardPage({ projectName }: { projectName: string }) {
  return <CreativeBoardWorkspace projectName={projectName} />;
}
