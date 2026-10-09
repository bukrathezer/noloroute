import { type DateRange, DayPicker, type Matcher } from "react-day-picker";
import { enGB } from "react-day-picker/locale/en-GB";
import { tr } from "react-day-picker/locale/tr";
import "react-day-picker/style.css";
import type { Lang } from "../i18n";

interface Props {
  lang: Lang;
  selected: DateRange | undefined;
  disabled: Matcher[];
  /** The first day while the last one is being picked. */
  pendingStart: Date | undefined;
  /** Days the trip would cover if the hovered day were clicked. */
  preview: DateRange | undefined;
  defaultMonth: Date;
  startMonth: Date;
  endMonth: Date;
  status: string;
  onPick: (day: Date) => void;
  onHover: (day: Date | null) => void;
}

/**
 * The month grid of the trip dates field. It lives in its own module so the calendar library is
 * downloaded the first time someone opens it, not with the rest of the page.
 */
export default function TripCalendar(props: Props) {
  return (
    <DayPicker
      mode="range"
      selected={props.selected}
      // The selection rules live in DateRangeField; DayPicker only reports the clicked day.
      onSelect={(_range, day) => props.onPick(day)}
      onDayMouseEnter={(day) => props.onHover(day)}
      onDayMouseLeave={() => props.onHover(null)}
      disabled={props.disabled}
      modifiers={{ departure: props.pendingStart ?? false, preview: props.preview }}
      modifiersClassNames={{ departure: "trip-start", preview: "trip-preview" }}
      locale={props.lang === "tr" ? tr : enGB}
      lang={props.lang}
      defaultMonth={props.defaultMonth}
      startMonth={props.startMonth}
      endMonth={props.endMonth}
      navLayout="around"
      autoFocus
      footer={props.status}
    />
  );
}
