import { useCallback, useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
import type { Tables } from "../lib/database.types";

type Conversation = Tables<"conversations">;

export function useConversations(userId: string | undefined) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    // Ordered by whichever is more recent: last message, or creation
    // time for a chat that has no messages yet.
    const { data, error } = await supabase
      .from("conversations")
      .select("*")
      .order("last_message_at", { ascending: false, nullsFirst: false })
      .order("updated_at", { ascending: false });
    if (!error && data) setConversations(data);
    setLoading(false);
  }, [userId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function createConversation(projectId: string | null = null): Promise<Conversation | null> {
    const { data, error } = await supabase
      .from("conversations")
      .insert({ project_id: projectId, title: "New Chat" })
      .select()
      .single();
    if (error || !data) return null;
    setConversations((prev) => [data, ...prev]);
    return data;
  }

  async function renameConversation(id: string, title: string) {
    await supabase.from("conversations").update({ title }).eq("id", id);
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
  }

  async function deleteConversation(id: string) {
    await supabase.from("conversations").delete().eq("id", id);
    setConversations((prev) => prev.filter((c) => c.id !== id));
  }

  return { conversations, loading, createConversation, renameConversation, deleteConversation, refresh };
}
