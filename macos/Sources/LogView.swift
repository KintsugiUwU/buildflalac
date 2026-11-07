import AppKit
import SwiftUI

/// The engine's log text: read-only and selectable, follows new lines while scrolled to the end.
struct LogView: NSViewRepresentable {
    @ObservedObject var log: LogBuffer

    final class Coordinator {
        var generation = -1
        /// How much of the log (in UTF-16 units) the text view shows.
        var shown = 0
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(context: Context) -> NSScrollView {
        let scrollView = NSTextView.scrollableTextView()
        scrollView.borderType = .bezelBorder
        scrollView.hasVerticalScroller = true
        scrollView.autohidesScrollers = true
        if let textView = scrollView.documentView as? NSTextView {
            textView.isEditable = false
            textView.isSelectable = true
            textView.isRichText = false
            textView.usesFindBar = true
            textView.font = Self.font
            textView.textColor = .labelColor
            textView.textContainerInset = NSSize(width: 2, height: 4)
        }
        return scrollView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        guard let textView = scrollView.documentView as? NSTextView,
              let storage = textView.textStorage else { return }
        let coordinator = context.coordinator
        let text = log.text as NSString
        let followEnd = Self.isScrolledToEnd(scrollView)
        if coordinator.generation != log.generation || text.length < coordinator.shown {
            storage.setAttributedString(NSAttributedString(string: log.text, attributes: Self.attributes))
        } else if text.length > coordinator.shown {
            let added = text.substring(from: coordinator.shown)
            storage.append(NSAttributedString(string: added, attributes: Self.attributes))
        } else {
            return
        }
        coordinator.generation = log.generation
        coordinator.shown = text.length
        if followEnd {
            textView.scrollToEndOfDocument(nil)
        }
    }

    private static let font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)

    private static var attributes: [NSAttributedString.Key: Any] {
        [.font: font, .foregroundColor: NSColor.labelColor]
    }

    private static func isScrolledToEnd(_ scrollView: NSScrollView) -> Bool {
        guard let document = scrollView.documentView else { return true }
        return scrollView.contentView.bounds.maxY >= document.frame.height - 24
    }
}
