import {
  flattenStructure,
  formatStep,
  type PlannedStep,
  type StructureItem,
  type Unit,
} from '../api'

export interface WorkoutGroup {
  steps: PlannedStep[]
  count: number
  recoveryBetween?: boolean
}

// Compare the prescribed values, never rounded display strings or expansion metadata.
function sameStep(a: PlannedStep | undefined, b: PlannedStep | undefined): boolean {
  return (
    !!a &&
    !!b &&
    a.type === b.type &&
    a.duration_type === b.duration_type &&
    a.duration_value === b.duration_value &&
    a.target?.modality === b.target?.modality &&
    a.target?.low === b.target?.low &&
    a.target?.high === b.target?.high &&
    a.target?.effort_cue === b.target?.effort_cue
  )
}

export function compactWorkout(structure: StructureItem[]): WorkoutGroup[] {
  const steps = flattenStructure(structure)
  const groups: WorkoutGroup[] = []
  for (let i = 0; i < steps.length;) {
    const work = steps[i],
      recovery = steps[i + 1]
    if (work.type === 'work' && recovery?.type === 'recovery') {
      let pairs = 1
      while (sameStep(work, steps[i + pairs * 2]) && sameStep(recovery, steps[i + pairs * 2 + 1]))
        pairs++
      const finalWork = sameStep(work, steps[i + pairs * 2])
      if (pairs > 1 || finalWork) {
        groups.push({
          steps: [work, recovery],
          count: pairs + (finalWork ? 1 : 0),
          recoveryBetween: finalWork,
        })
        i += pairs * 2 + (finalWork ? 1 : 0)
        continue
      }
    }
    // Other exact repeated sequences (including explicit repeat blocks).
    let found = false
    for (let width = 1; width <= (steps.length - i) / 2; width++) {
      let count = 1
      while (
        i + (count + 1) * width <= steps.length &&
        steps.slice(i, i + width).every((step, j) => sameStep(step, steps[i + count * width + j]))
      )
        count++
      if (count < 2) continue
      groups.push({ steps: steps.slice(i, i + width), count })
      i += width * count
      found = true
      break
    }
    if (!found) {
      groups.push({ steps: [work], count: 1 })
      i++
    }
  }
  return groups
}

function stepText(step: PlannedStep, unit: Unit): string {
  const text = formatStep(step, unit)
  const cue = step.target?.effort_cue?.trim()
  return cue && step.target?.modality !== 'effort' ? `${text} · ${cue}` : text
}

export function WorkoutStructure({ structure, unit }: { structure: StructureItem[]; unit: Unit }) {
  return (
    <ol className="compact-workout">
      {compactWorkout(structure).map((group, index) => (
        <li key={index}>
          {group.count === 1 ? (
            stepText(group.steps[0], unit)
          ) : group.recoveryBetween ? (
            <>
              <strong>{group.count} ×</strong> {stepText(group.steps[0], unit)}
              <div>
                Between reps ({group.count - 1} recoveries): {stepText(group.steps[1], unit)}
              </div>
            </>
          ) : (
            <>
              <strong>{group.count} ×</strong>
              <ul>
                {group.steps.map((step, j) => (
                  <li key={j}>{stepText(step, unit)}</li>
                ))}
              </ul>
              {group.steps.at(-1)?.type === 'recovery' && (
                <small>Recovery after every rep, including the final rep.</small>
              )}
            </>
          )}
        </li>
      ))}
    </ol>
  )
}
