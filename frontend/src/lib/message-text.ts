/** Text helpers shared between the message renderer and voice output. */

/** Remove <think> reasoning blocks so they are neither shown nor spoken. */
export function stripThinkTags(text: string): string {
  let cleaned = text.replace(/<think>[\s\S]*?<\/think>\s*/gi, '');
  cleaned = cleaned.replace(/^[\s\S]*?<\/think>\s*/i, '');
  return cleaned.trim();
}

/** Prepare prose for neural speech without reading Markdown punctuation. */
export function cleanSpeechText(text: string): string {
  return stripThinkTags(text)
    .replace(/```[\s\S]*?```|~~~[\s\S]*?~~~/g, '')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/<[^>]+>/g, '')
    .replace(/^\s*(?:#{1,6}\s+|>\s*|[-+*]\s+|\d+[.)]\s+)/gm, '')
    .replace(/[*_`~#|]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}
