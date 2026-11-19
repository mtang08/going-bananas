import { Button } from '../../components/ui'

export function DecisionActions({
  hasChanges,
  acceptDisabled,
  rejectDisabled,
  discardDisabled,
  discardPending,
  confirmDiscard,
  onAccept,
  onRejectAll,
  onAskDiscard,
  onConfirmDiscard,
  onCancelDiscard,
}: {
  hasChanges: boolean
  acceptDisabled: boolean
  rejectDisabled: boolean
  discardDisabled: boolean
  discardPending: boolean
  confirmDiscard: boolean
  onAccept: () => void
  onRejectAll: () => void
  onAskDiscard: () => void
  onConfirmDiscard: () => void
  onCancelDiscard: () => void
}) {
  return (
    <>
      <div className="proposal-actions">
        <Button disabled={acceptDisabled} onClick={onAccept}>
          {hasChanges ? 'Accept selected' : 'Accept (no changes)'}
        </Button>
        {hasChanges && (
          <Button variant="outline" disabled={rejectDisabled} onClick={onRejectAll}>
            Reject all
          </Button>
        )}
      </div>
      <div className="proposal-secondary" data-testid="proposal-secondary">
        <p className="fineprint">
          Reject all keeps this proposal in history. Discard removes it without a decision.
        </p>
        {confirmDiscard ? (
          <div className="notice warning">
            <p>
              Discard this proposal? It will be removed from the open list. The calendar will not
              change.
            </p>
            <Button
              variant="outline"
              disabled={discardDisabled}
              onClick={() => {
                if (!discardDisabled) onConfirmDiscard()
              }}
            >
              Confirm discard
            </Button>{' '}
            <Button variant="outline" disabled={discardPending} onClick={onCancelDiscard}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button variant="link" disabled={discardDisabled} onClick={onAskDiscard}>
            Discard proposal
          </Button>
        )}
      </div>
    </>
  )
}
