# WixDesignSystem (@wix/design-system@1.286.0)

This design system is the published @wix/design-system React library, bundled as a single
browser global. All 209 components are the real upstream code.

## Where things are

- `_ds_bundle.js` — the whole-DS bundle at the project root; loads every component to `window.WixDesignSystem`. First line is a `/* @ds-bundle: … */` metadata header.
- `styles.css` — the single stylesheet entry: it `@import`s the tokens, fonts, and component styles (`_ds_bundle.css`). Link this one file.
- `components/<group>/<Name>/<Name>.prompt.md` (example JSX + variants), `<Name>.d.ts` (types), `<Name>.html` (variant grid).
- `tokens/*.css` — CSS custom properties, names verbatim from upstream.
- `fonts/` — `@font-face` files + `fonts.css` (when the package ships fonts).

For a specific component, `read_file("components/<group>/<Name>/<Name>.prompt.md")`.

## Loading

Add these two lines to your page once (React must be on the page first):

```html
<link rel="stylesheet" href="styles.css">
<script src="_ds_bundle.js"></script>
```

Components are then available at `window.WixDesignSystem.*`. Mount into a dedicated child node (e.g. `<div id="ds-root">`), not the host page's own React root, so the two trees don't collide:

```jsx
const { Accordion } = window.WixDesignSystem;
ReactDOM.createRoot(document.getElementById('ds-root')).render(<Accordion />);
```

## Tokens

2128 CSS custom properties from @wix/design-system-tokens. Names are
preserved verbatim from upstream. See `tokens/` for the full list.

- **color** (1135): `--wds-color-text-stage-section`, `--wds-color-fill-stage-section-secondary-hover`, `--wds-color-fill-stage-section-secondary-active`, …
- **spacing** (409): `--wds-space-2400`, `--wds-space-1700`, `--wds-space-1600`, …
- **typography** (199): `--wds-font-weight-semi-bold`, `--wds-font-weight-regular`, `--wds-font-weight-medium`, …
- **radius** (86): `--wds-border-radius-full`, `--wds-border-radius-1200`, `--wds-border-radius-600`, …
- **shadow** (129): `--wds-shadow-spread-secondary-raised`, `--wds-shadow-focus-spread`, `--wds-shadow-y-600`, …
- **other** (170): `--wds-breakpoint-x-large`, `--wds-breakpoint-small`, `--wds-breakpoint-medium`, …

## Components

### lists
- `Accordion`
- `CardGalleryItem`
- `EditableSelector`
- `HorizontalTimeline`
- `NestableList`
- `NestableListBase`
- `SelectableAccordion`
- `Selector` (compound: `Selector.ExtraText`, `Selector.ProgressBar`)
- `SelectorList`
- `SelectorListContent`
- `SortableGridBase`
- `Table`
- `TableActionCell`
- `TableListHeader`
- `TableListItem`
- `TableToolbar` (compound: `TableToolbar.ItemGroup`, `TableToolbar.Item`, `TableToolbar.Title`, `TableToolbar.Label`, `TableToolbar.Divider`, `TableToolbar.SelectedCount`)
- `TagList`
- `Timeline`
- `TimeTable`

### actions
- `AddItem`
- `Button`
- `CloseButton`
- `ComposerButton`
- `IconButton`
- `SelectorButton`
- `SocialButton`
- `SplitAction`
- `TextButton`
- `ToggleButton`

### forms
- `AddressInput`
- `AddressInputItem` — This component is used to display an address item mainly in AddressInput/ component.
- `AngleInput`
- `AutoComplete`
- `AutoCompleteWithLabel`
- `Calendar`
- `CalendarPanel`
- `CalendarPanelFooter`
- `Checkbox`
- `CheckToggle`
- `ColorInput`
- `ColorPicker`
- `CornerRadiusInput` — input component used for entering corner radius value for each corner of an element
- `DatePicker`
- `Dropdown`
- `DropdownBase`
- `DropdownLayout`
- `Dropzone`
- `FacesRatingBar`
- `FieldSet`
- `FilePicker`
- `FileUpload`
- `FillButton`
- `FillPreview`
- `FormField`
- `GoogleAddressInput`
- `InfoIcon`
- `Input` (compound: `Input.Ticker`, `Input.IconAffix`, `Input.Affix`, `Input.Group`)
- `InputArea` — General inputArea container
- `InputShell` — A wrapper component that has a style of an input component
- `InputWithLabel`
- `InputWithOptions`
- `ListItemAction`
- `ListItemEditable`
- `ListItemSection`
- `ListItemSelect`
- `ListItemSelectIcon`
- `MultiSelect`
- `MultiSelectCheckbox`
- `NumberInput`
- `Palette`
- `Radio`
- `RadioGroup` — component for easy radio group creation.
- `Range`
- `RichTextInputArea`
- `Search`
- `SegmentedToggle`
- `Slider`
- `StarsRatingBar`
- `StatusIndicator`
- `Swatches`
- `Tag`
- `Thumbnail`
- `TimeInput`
- `ToggleSwitch`
- `VariableInput`

### charts
- `AnalyticsLayout` — AnalyticsLayout
- `AnalyticsSummaryCard`
- `AreaChart`
- `BarChart`
- `FunnelChart`
- `RadarChart`
- `SparklineChart`
- `StackedBarChart`
- `StatisticsWidget`
- `TrendIndicator`

### overlays
- `AnnouncementModalLayout` — A layout for announcement modals, to be used inside a ltModal /gt
- `CustomModalLayout` (compound: `CustomModalLayout.Title`)
- `Drawer`
- `FloatingHelper`
- `FullScreenModalLayout` (compound: `FullScreenModalLayout.Header`, `FullScreenModalLayout.Content`, `FullScreenModalLayout.Footer`)
- `MessageBoxFunctionalLayout`
- `MessageBoxMarketerialLayout`
- `MessageModalLayout`
- `Modal`
- `ModalMobileLayout`
- `ModalPreviewLayout`
- `ModalSelectorLayout`
- `Popover`
- `PopoverMenu` (compound: `PopoverMenu.MenuItem`, `PopoverMenu.Divider`, `PopoverMenu.SectionTitle`)
- `SidePanel`
- `Tooltip`

### media
- `AudioPlayer`
- `Avatar`
- `AvatarGroup`
- `BrowserPreviewWidget` — Browser preview widget
- `Carousel`
- `CarouselWIP` — The carousel component creates a slideshow for cycling through a series of content.
- `CodeSnippet`
- `GooglePreview`
- `Image`
- `ImageViewer`
- `MediaOverlay`
- `MobilePreviewWidget`
- `PreviewWidget`
- `SocialPostPreview` — SocialPostPreview
- `SocialPreview`

### feedback
- `Badge`
- `BadgeSelect`
- `CircularProgressBar`
- `CounterBadge` — CounterBadge
- `FloatingNotification`
- `LinearProgressBar`
- `LiveRegion` — LiveRegion
- `Loader`
- `NavigationToast`
- `Notification`
- `SectionHelper`
- `Skeleton`
- `SkeletonCircle` — SkeletonCircle
- `SkeletonGroup` — SkeletonGroup
- `SkeletonLine`
- `SkeletonRectangle`
- `StatusToast` (compound: `StatusToast.Action`, `StatusToast.Link`)
- `Toast`
- `ToastContainer`
- `TopBanner` (compound: `TopBanner.ActionButton`, `TopBanner.ActionLink`)

### animations
- `BounceAnimation` — Bounce Animation
- `PulseAnimation` — PulseAnimation
- `Transition` — Transition is a wrapper that allows animations of other components.

### layout
- `Box`
- `Card` (compound: `Card.Content`, `Card.Header`, `Card.Divider`, `Card.Subheader`)
- `CardFolderTabs`
- `ClickableCard` (compound: `ClickableCard.Action`)
- `Divider`
- `EditableTitle`
- `EmptyState` — Representing a state of an empty page, section, table, etc.
- `FeatureList`
- `Layout`
- `MarketingLayout` — Marketing layout is a layout designed to promote new features or display first time visit.
- `MarketingPageLayout` — Marketing Page Layout
- `MarketingPageLayoutContent` — This component is used in the MarketingPageLayout component. It includes all the content of the page.
- `Page`
- `PageFooter` — Layout footer component of 3 columns
- `PageHeader` — A header that sticks at the top of the container which minimizes on scroll
- `PageSection`
- `SectionHeader`
- `TestimonialList`

### navigation
- `Breadcrumbs`
- `ComposerHeader`
- `ComposerSidebar`
- `Pagination`
- `Sidebar`
- `SidebarBackButton`
- `SidebarDivider`
- `SidebarDividerNext` — A divider within the sidebar that supports inner and full mode
- `SidebarHeader`
- `SidebarHeaderNext`
- `SidebarItemNext`
- `SidebarNext`
- `SidebarSectionItem`
- `SidebarSectionTitle`
- `SidebarSubMenuNext`
- `SidebarTitleItemNext`
- `Stepper`
- `Tabs`
- `VerticalTabs` (compound: `VerticalTabs.TabsGroup`, `VerticalTabs.Footer`)
- `VerticalTabsIconItem`
- `VerticalTabsItem`

### analyticslayout
- `Cell`

### mechanisms
- `Collapse` — Use Collapse/ for hideable content.
- `CopyClipboard`
- `Highlighter`
- `HorizontalScroll`
- `Proportion`
- `SortableListBase`

### providers
- `DragDropContextProvider`
- `SidebarContextConsumer`
- `SidebarItemContextConsumer`
- `ThemeProvider`
- `WixDesignSystemIconThemeProvider`
- `WixDesignSystemProvider`
- `WixStyleReactDefaultsOverrideProvider`
- `WixStyleReactEnvironmentProvider` — A wrapper component for an app to hold cross library global configuration such as locale, rtl and others
- `WixStyleReactMaskingProvider`

### typography
- `Heading`
- `Text`

### splitaction
- `SplitActionButton`
- `SplitActionIconButton`

### table
- `TableFloatingScrollBar`
