export const WEEKLY_PROMPT =
  'Use $going-bananas-coach for my Sunday review in real mode. Check whether I need a block review or the regular next-14-days review, and prepare a proposal. My schedule changes and feedback are: …'
export const EXCEPTION_PROMPT =
  'Use $going-bananas-coach for an exception review. Read the open findings in the app and patch only what they require.'
export const BLOCK_PROMPT =
  'Use $going-bananas-coach for a block review. An exception needs a bigger review.'
export const REASSESS_PROMPT = 'Use $going-bananas-coach to reassess the open exception patch.'
export const racePrompt = (eventName: string, eventDate: string): string =>
  `Use $going-bananas-coach for a post-race review of ${eventName} on ${eventDate}.`
