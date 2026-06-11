import { create } from "zustand";
import { persist } from "zustand/middleware";

// CR-004-H: the selected project context persists across global pages and reloads.
interface ProjectState {
  activeProjectId: string | null;
  activeProjectName: string | null;
  setActiveProject: (id: string, name: string) => void;
  clearActiveProject: () => void;
}

export const useProjectStore = create<ProjectState>()(
  persist(
    (set) => ({
      activeProjectId: null,
      activeProjectName: null,
      setActiveProject: (id, name) => set({ activeProjectId: id, activeProjectName: name }),
      clearActiveProject: () => set({ activeProjectId: null, activeProjectName: null }),
    }),
    { name: "yapi-active-project" }
  )
);
