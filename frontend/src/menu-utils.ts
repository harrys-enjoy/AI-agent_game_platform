export type MenuSelection = { type: "section" | "chat"; id: string };
export type MenuState = { activeSection: string; activeChat: string | null };

export function selectMenu(selection: MenuSelection, currentSection = "Home"): MenuState {
  return selection.type === "chat"
    ? { activeSection: currentSection, activeChat: selection.id }
    : { activeSection: selection.id === "Policies" ? "Policies" : "Home", activeChat: null };
}
