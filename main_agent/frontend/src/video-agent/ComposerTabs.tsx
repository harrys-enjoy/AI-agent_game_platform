import * as Tabs from "@radix-ui/react-tabs";
import { useState, type ReactNode } from "react";

export function ComposerTabs({ chat, form }: { chat: ReactNode; form: ReactNode }) {
  const [value, setValue] = useState("chat");

  return (
    <Tabs.Root value={value} onValueChange={setValue} className="flex flex-col gap-3">
      <Tabs.List className="flex gap-2" aria-label="브리프 작성 방식">
        <Tabs.Trigger
          value="chat"
          className="rounded-[8px] px-3 py-1 text-sm text-brief-text data-[state=active]:bg-brief-accent data-[state=active]:text-white"
        >
          채팅
        </Tabs.Trigger>
        <Tabs.Trigger
          value="form"
          className="rounded-[8px] px-3 py-1 text-sm text-brief-text data-[state=active]:bg-brief-accent data-[state=active]:text-white"
        >
          폼
        </Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="chat" forceMount hidden={value !== "chat"}>
        {chat}
      </Tabs.Content>
      <Tabs.Content value="form" forceMount hidden={value !== "form"}>
        {form}
      </Tabs.Content>
    </Tabs.Root>
  );
}
