# Legacy inbox migration

Use the old project inbox only as a temporary control and recovery channel.

Cut over one agent at a time. An unconfirmed agent remains on its legacy policy
even when another agent has migrated.

For each agent:

1. Install AgentPost, register its project identity, and run static doctor from
   that project.
2. Send one uniquely identified acceptance request through AgentPost only.
3. Verify that agent receives and claims the exact Message-ID, exercises
   identity/directory resolution, and returns an outbound AgentPost report that
   the originator receives.
4. If the old session cannot see the new plugin, place a control note in the old
   inbox telling it to reload and naming the existing AgentPost Message-ID.
5. Send that agent an individual migration directive through AgentPost. Do not
   use a group directive as evidence that every member is ready.
6. Have the agent update its durable project instructions so AgentPost is the
   primary cross-agent channel, actionable legacy delivery is prohibited, and
   the legacy inbox is retained as read-only history/recovery only.
7. Stop that agent's legacy polling process. Replace ad hoc AgentPost polling
   with its native monitor/runtime so presence and attention boundaries remain
   truthful.
8. Verify one post-cutover direct message, correlated reply, restart catch-up,
   immediate behavior, and idle deferral. If this fails, restore only that
   agent's legacy control path without duplicating the actionable message.

After every agent independently passes, retire any remaining shared legacy
watcher. Retain the old folders as read-only history until separately archived.

Never copy the request body into both systems. Two actionable copies are two
jobs, and an agent may correctly perform both.

If a native notification fails, the fallback note must say that it is control
only and point to the already-existing Message-ID. Once the new path is proven,
all normal direct messages, reviews, group questions, and replies use AgentPost.
