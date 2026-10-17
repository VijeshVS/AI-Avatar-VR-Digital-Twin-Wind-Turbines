using System;
using System.Collections.Generic;

namespace Vrar.Presentation
{
    /// <summary>
    /// Which component the readout is currently inspecting.
    ///
    /// Plain C# on purpose: focus is a selection rule, not a rendering concern,
    /// so it can be asserted without an IMGUI event stream. Selection survives a
    /// change in the component list only if the id is still present.
    /// </summary>
    public sealed class ComponentFocus
    {
        private readonly List<string> _order = new List<string>();

        public string ComponentId { get; private set; }
        public bool HasFocus { get; private set; }
        public int Index { get; private set; } = -1;

        public event Action Changed;

        public int Count => _order.Count;

        public string this[int index] => _order[index];

        /// <summary>
        /// Rebuild the selectable order. A selection that survives the rebuild is
        /// kept; one that has disappeared is dropped rather than left dangling.
        /// </summary>
        public void SetOrder(IReadOnlyList<string> componentIds)
        {
            bool sameOrder = _order.Count == componentIds.Count;
            if (sameOrder)
            {
                for (int i = 0; i < _order.Count; i++)
                {
                    if (_order[i] != componentIds[i])
                    {
                        sameOrder = false;
                        break;
                    }
                }
            }

            if (sameOrder)
            {
                return;
            }

            string previous = ComponentId;
            _order.Clear();
            for (int i = 0; i < componentIds.Count; i++)
            {
                _order.Add(componentIds[i]);
            }

            if (previous != null && _order.Contains(previous))
            {
                Index = _order.IndexOf(previous);
                return;
            }

            Clear();
        }

        public void Select(int index)
        {
            if (index < 0 || index >= _order.Count)
            {
                return;
            }

            if (Index == index && HasFocus)
            {
                return;
            }

            Index = index;
            ComponentId = _order[index];
            HasFocus = true;
            Changed?.Invoke();
        }

        public void Select(string componentId)
        {
            int index = _order.IndexOf(componentId);
            if (index >= 0)
            {
                Select(index);
            }
        }

        /// <summary>Step through the components, wrapping at both ends.</summary>
        public void Cycle(int delta)
        {
            if (_order.Count == 0)
            {
                return;
            }

            int next = HasFocus ? Index + delta : delta > 0 ? 0 : _order.Count - 1;
            next = ((next % _order.Count) + _order.Count) % _order.Count;
            Select(next);
        }

        public void Clear()
        {
            if (!HasFocus && Index < 0)
            {
                return;
            }

            HasFocus = false;
            Index = -1;
            ComponentId = null;
            Changed?.Invoke();
        }
    }
}