/**
 * heuristics.ts — "I Think It Should Be Enhanced, Because..." Heuristic Generator
 *
 * Post-Audit UX & Friction Analyzer:
 * Discovered defects are not limited to hard exceptions or crashes. Latent UX defects,
 * cognitive friction, and missing guards degrade agent and human efficiency.
 *
 * Evaluates 4 Critical Vectors:
 * 1. Form validation states (missing debounced pre-validation)
 * 2. Destructive action confirmation guards
 * 3. Empty-state affordances and guidance copy
 * 4. Dynamic loading feedback on async mutations
 */

export interface EnhancementItem {
  id: string
  subsystem: string
  feature: string
  routeOrComponent: string
  category: "validation" | "destructive_guard" | "empty_state" | "async_feedback" | "a11y"
  currentBehavior: string
  rationale: string
  proposedEnhancement: string
  expectedImpact: string
}

export interface FormInspectionSubject {
  route: string
  formName: string
  hasInlineDebounce: boolean
  hasValidationFeedback: boolean
  hasClearErrorState: boolean
}

export interface DestructiveActionSubject {
  route: string
  actionName: string
  hasConfirmationModal: boolean
  hasCancelDefaultFocus: boolean
}

export interface EmptyStateSubject {
  route: string
  containerName: string
  itemCount: number
  hasActionableCta: boolean
  hasStarterTemplates: boolean
  displayedCopy?: string
}

export interface AsyncMutationSubject {
  route: string
  actionName: string
  displaysLoadingSpinner: boolean
  disablesButtonOnSubmit: boolean
}

export class HeuristicEngine {
  private enhancements: EnhancementItem[] = []

  /**
   * Inspects a form for debounced validation and immediate inline feedback.
   */
  inspectFormValidation(subject: FormInspectionSubject): EnhancementItem | null {
    if (!subject.hasInlineDebounce || !subject.hasValidationFeedback) {
      const item: EnhancementItem = {
        id: `ENH-FORM-${Date.now().toString(36)}`,
        subsystem: subject.route,
        feature: subject.formName,
        routeOrComponent: subject.route,
        category: "validation",
        currentBehavior: `Form submission for ${subject.formName} only performs validation upon final submit button press without debounced inline hints.`,
        rationale: `I think it should be enhanced, because users and automated agents only discover invalid field constraints after clicking submit and enduring round-trip errors, increasing error-correction loops and cognitive friction.`,
        proposedEnhancement: `Implement debounced inline pre-validation (300ms delay) with realtime checkmarks and explanatory error hints.`,
        expectedImpact: `Eliminates failed submit roundtrips and prevents form submission errors upfront.`,
      }
      this.enhancements.push(item)
      return item
    }
    return null
  }

  /**
   * Inspects high-risk destructive actions for modal confirmation protection.
   */
  inspectDestructiveGuard(subject: DestructiveActionSubject): EnhancementItem | null {
    if (!subject.hasConfirmationModal || !subject.hasCancelDefaultFocus) {
      const item: EnhancementItem = {
        id: `ENH-GUARD-${Date.now().toString(36)}`,
        subsystem: subject.route,
        feature: subject.actionName,
        routeOrComponent: subject.route,
        category: "destructive_guard",
        currentBehavior: `Action '${subject.actionName}' executes without a confirmation dialog or lacks default focus on 'Cancel'.`,
        rationale: `I think it should be enhanced, because destructive operations (deletions, purges, rotations) are irreversible. A single misclick by a user or agent immediately destroys data without an undo buffer.`,
        proposedEnhancement: `Wrap ${subject.actionName} in a high-contrast <ConfirmModal> dialog with explicit action name input and default focus pinned to 'Cancel'.`,
        expectedImpact: `Zero accidental data loss or cascading resource purges.`,
      }
      this.enhancements.push(item)
      return item
    }
    return null
  }

  /**
   * Inspects initial/cleared screen states for empty state affordances.
   */
  inspectEmptyState(subject: EmptyStateSubject): EnhancementItem | null {
    if (subject.itemCount === 0 && (!subject.hasActionableCta || !subject.hasStarterTemplates)) {
      const item: EnhancementItem = {
        id: `ENH-EMPTY-${Date.now().toString(36)}`,
        subsystem: subject.route,
        feature: subject.containerName,
        routeOrComponent: subject.route,
        category: "empty_state",
        currentBehavior: `When 0 records exist, ${subject.containerName} displays "${subject.displayedCopy ?? 'No items'}" without starter templates or actionable guidance.`,
        rationale: `I think it should be enhanced, because an unguided empty state leaves new users at a loss for how to structure their first resource, increasing time-to-first-value and bounce rates.`,
        proposedEnhancement: `Render an illustrated Empty State card with 2-3 starter blueprint cards (e.g. 'Daily Health Report', 'Slack Alerter') and an unambiguous primary 'Create' button.`,
        expectedImpact: `Reduces initial setup friction and accelerates time to first successful configuration.`,
      }
      this.enhancements.push(item)
      return item
    }
    return null
  }

  /**
   * Inspects asynchronous mutations for instant loading feedback.
   */
  inspectAsyncFeedback(subject: AsyncMutationSubject): EnhancementItem | null {
    if (!subject.displaysLoadingSpinner || !subject.disablesButtonOnSubmit) {
      const item: EnhancementItem = {
        id: `ENH-ASYNC-${Date.now().toString(36)}`,
        subsystem: subject.route,
        feature: subject.actionName,
        routeOrComponent: subject.route,
        category: "async_feedback",
        currentBehavior: `Triggering '${subject.actionName}' does not immediately disable the button or display an inline loading indicator during pending network flight.`,
        rationale: `I think it should be enhanced, because absence of immediate visual feedback causes impatient users and fast agents to click the button multiple times, causing race conditions and duplicate database inserts.`,
        proposedEnhancement: `Apply immediate disabled state (\`disabled={isPending}\`) and append an inline SVG spinner or pulsating progress bar.`,
        expectedImpact: `Prevents double-click race conditions and reassures users that their mutation is actively being processed.`,
      }
      this.enhancements.push(item)
      return item
    }
    return null
  }

  getEnhancements(): readonly EnhancementItem[] {
    return this.enhancements
  }

  /**
   * Formats all accumulated enhancements into canonical Markdown documentation.
   */
  formatMarkdown(): string {
    if (this.enhancements.length === 0) {
      return "*(No enhancement heuristics flagged. All surfaces meet high UX & resilience standards.)*\n"
    }

    const lines: string[] = [
      "## Discovered UX Enhancements (\"I Think It Should Be Enhanced, Because...\")",
      "",
    ]

    for (const enh of this.enhancements) {
      lines.push(`### Feature: ${enh.feature} (\`${enh.routeOrComponent}\`)`)
      lines.push(`- **Current Behavior**: ${enh.currentBehavior}`)
      lines.push(`- **"I Think It Should Be Enhanced, Because..."**: ${enh.rationale}`)
      lines.push(`- **Proposed Enhancement**: ${enh.proposedEnhancement}`)
      lines.push(`- **Expected Impact**: ${enh.expectedImpact}`)
      lines.push("")
    }

    return lines.join("\n")
  }
}
