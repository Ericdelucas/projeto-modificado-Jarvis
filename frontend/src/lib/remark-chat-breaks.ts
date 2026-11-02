/** Preserve chat soft line breaks without changing code, math or block structure. */
interface MarkdownNode {
  type: string;
  value?: string;
  children?: MarkdownNode[];
}

export function remarkChatBreaks() {
  return (tree: MarkdownNode): void => {
    const visit = (parent: MarkdownNode): void => {
      if (!parent.children) return;
      parent.children = parent.children.flatMap((node) => {
        if (node.type === 'text' && node.value?.includes('\n')) {
          const lines = node.value.split(/\r?\n/);
          return lines.flatMap((line, index): MarkdownNode[] => [
            ...(index ? [{ type: 'break' }] : []),
            ...(line ? [{ type: 'text', value: line }] : []),
          ]);
        }
        visit(node);
        return [node];
      });
    };
    visit(tree);
  };
}
