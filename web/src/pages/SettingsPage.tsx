import { useState } from "react";
import type { User } from "../api";
import { Segmented, type SegmentOption } from "../components/Segmented";
import { AccountTab } from "./settings/AccountTab";
import { AuditTab } from "./settings/AuditTab";
import { GeneralTab } from "./settings/GeneralTab";
import { IssuesTab } from "./settings/IssuesTab";
import { SystemTab } from "./settings/SystemTab";
import { UsersTab } from "./settings/UsersTab";
import { useSettingsData } from "./settings/useSettingsData";
import "./settings/Settings.css";

type Tab = "account" | "general" | "system" | "users" | "audit" | "issues";

const FOR_EVERYONE: SegmentOption<Tab>[] = [
  { value: "account", label: "Account" },
  { value: "general", label: "General" },
];
// The server refuses these sections' routes to anyone else; leaving them out is only tidiness.
const FOR_ADMINS: SegmentOption<Tab>[] = [
  { value: "system", label: "System" },
  { value: "users", label: "Users" },
  { value: "audit", label: "Audit log" },
  { value: "issues", label: "Issues" },
];
const WIDE: Tab[] = ["users", "audit", "issues"];

export function SettingsPage({ user }: { user: User }) {
  const [tab, setTab] = useState<Tab>("account");
  const data = useSettingsData();
  const tabs = user.is_admin ? [...FOR_EVERYONE, ...FOR_ADMINS] : FOR_EVERYONE;

  return (
    <>
      <div className="page-header">
        <h1>Settings</h1>
      </div>
      <div className="settings-tabs">
        <Segmented label="Section" onPage options={tabs} value={tab} onChange={setTab} />
      </div>
      <div className={WIDE.includes(tab) ? "settings-col" : "narrow"}>
        {tab === "account" && <AccountTab user={user} />}
        {tab === "general" && <GeneralTab data={data} locked={!user.is_admin} />}
        {user.is_admin && tab === "system" && <SystemTab data={data} />}
        {user.is_admin && tab === "users" && <UsersTab me={user} />}
        {user.is_admin && tab === "audit" && <AuditTab />}
        {user.is_admin && tab === "issues" && <IssuesTab />}
      </div>
    </>
  );
}
