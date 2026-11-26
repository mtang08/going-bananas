"""Project reference rule context for the Python/Go differential corpus."""


def rule_inputs(doc, ctx):
    return {
        "rule_context": {
            "today": ctx.today,
            "timezone": str(ctx.tz),
            "guard": ctx.current_safety_guard,
            "interruption": ctx.running_interruption.model_dump(mode="json")
            if ctx.running_interruption
            else None,
            "restriction": ctx.running_restriction.model_dump(mode="json")
            if ctx.running_restriction
            else None,
            "eligible_recipes": ctx.active_block.eligible_recipe_ids
            if ctx.active_block
            else [],
            "cycle_anchor": ctx.cycle_anchor,
            "review_date": ctx.active_block.review_date if ctx.active_block else None,
            "confirmed_dates": {str(x): True for x in ctx.confirmed_strength_dates},
            "omitted_dates": {
                str(x): True for x in ctx.accepted_strength_omission_dates
            },
            "confirmed_slots": {
                str(k): str(v) for k, v in ctx.confirmed_strength_slot_ids.items()
            },
            "omitted_slots": {
                str(k): str(v)
                for k, v in ctx.accepted_strength_omission_slot_ids.items()
            },
            "block_uid": str(ctx.active_block.block_uid) if ctx.active_block else "",
            "head_sessions": {
                str(uid): vars(row) for uid, row in ctx.head_sessions.items()
            },
            "findings": {str(k): v for k, v in ctx.findings.items()},
            "patches": {str(k): v for k, v in ctx.patches.items()},
            "events": {
                str(k): {
                    "status": v[0],
                    "day": v[1],
                    "rank": v[2] if len(v) > 2 else None,
                }
                for k, v in ctx.events.items()
            },
            "open_rule_codes": sorted(ctx.open_rule_codes),
            "benchmark": {
                k: getattr(ctx.benchmark, k, None)
                for k in ("status", "activity_id", "event_id", "local_date")
            }
            if ctx.benchmark
            else None,
            "last_benchmark_date": ctx.last_benchmark_date,
        },
    }
