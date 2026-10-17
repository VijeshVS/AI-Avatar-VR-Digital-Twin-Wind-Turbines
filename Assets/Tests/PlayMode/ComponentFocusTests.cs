using System.Collections.Generic;
using NUnit.Framework;
using Vrar.Presentation;

namespace Vrar.Tests
{
    /// <summary>
    /// Focus is a selection rule, not a rendering concern, so it is tested
    /// without an IMGUI event stream: select, switch, and survive the component
    /// list changing underneath it.
    /// </summary>
    public class ComponentFocusTests
    {
        private static List<string> Ids(params string[] ids) => new List<string>(ids);

        [Test]
        public void StartsWithNoSelection()
        {
            var focus = new ComponentFocus();

            Assert.IsFalse(focus.HasFocus);
            Assert.AreEqual(-1, focus.Index);
            Assert.IsNull(focus.ComponentId);
        }

        [Test]
        public void SelectByIndexSetsTheComponentId()
        {
            var focus = new ComponentFocus();
            focus.SetOrder(Ids("blade_set", "gearbox", "generator"));

            focus.Select(1);

            Assert.IsTrue(focus.HasFocus);
            Assert.AreEqual(1, focus.Index);
            Assert.AreEqual("gearbox", focus.ComponentId);
        }

        [Test]
        public void SelectByIdResolvesToItsIndex()
        {
            var focus = new ComponentFocus();
            focus.SetOrder(Ids("blade_set", "gearbox", "generator"));

            focus.Select("generator");

            Assert.AreEqual(2, focus.Index);
            Assert.AreEqual("generator", focus.ComponentId);
        }

        [Test]
        public void OutOfRangeAndUnknownSelectionsAreIgnored()
        {
            var focus = new ComponentFocus();
            focus.SetOrder(Ids("blade_set", "gearbox"));

            focus.Select(7);
            focus.Select(-1);
            focus.Select("yaw_system");

            Assert.IsFalse(focus.HasFocus);
        }

        [Test]
        public void CycleStartsAtTheFirstComponentThenWraps()
        {
            var focus = new ComponentFocus();
            focus.SetOrder(Ids("a", "b", "c"));

            focus.Cycle(1);
            Assert.AreEqual("a", focus.ComponentId);

            focus.Cycle(1);
            focus.Cycle(1);
            Assert.AreEqual("c", focus.ComponentId);

            focus.Cycle(1);
            Assert.AreEqual("a", focus.ComponentId);
        }

        [Test]
        public void CycleBackwardsFromNoSelectionStartsAtTheLast()
        {
            var focus = new ComponentFocus();
            focus.SetOrder(Ids("a", "b", "c"));

            focus.Cycle(-1);

            Assert.AreEqual("c", focus.ComponentId);
        }

        [Test]
        public void ClearDropsTheSelection()
        {
            var focus = new ComponentFocus();
            focus.SetOrder(Ids("a", "b"));
            focus.Select(0);

            focus.Clear();

            Assert.IsFalse(focus.HasFocus);
            Assert.AreEqual(-1, focus.Index);
            Assert.IsNull(focus.ComponentId);
        }

        [Test]
        public void SelectionSurvivesAnUnchangedOrder()
        {
            var focus = new ComponentFocus();
            focus.SetOrder(Ids("a", "b", "c"));
            focus.Select(2);

            focus.SetOrder(Ids("a", "b", "c"));

            Assert.IsTrue(focus.HasFocus);
            Assert.AreEqual(2, focus.Index);
            Assert.AreEqual("c", focus.ComponentId);
        }

        [Test]
        public void SelectionSurvivesAReorderedList()
        {
            var focus = new ComponentFocus();
            focus.SetOrder(Ids("a", "b", "c"));
            focus.Select("b");

            focus.SetOrder(Ids("c", "b", "a"));

            Assert.IsTrue(focus.HasFocus);
            Assert.AreEqual("b", focus.ComponentId);
            Assert.AreEqual(1, focus.Index);
        }

        [Test]
        public void SelectionIsDroppedWhenItsComponentDisappears()
        {
            var focus = new ComponentFocus();
            focus.SetOrder(Ids("a", "b", "c"));
            focus.Select("b");

            focus.SetOrder(Ids("a", "c"));

            Assert.IsFalse(focus.HasFocus);
            Assert.AreEqual(-1, focus.Index);
        }

        [Test]
        public void ChangingRaisesTheChangedEvent()
        {
            var focus = new ComponentFocus();
            focus.SetOrder(Ids("a", "b"));
            int changes = 0;
            focus.Changed += () => changes++;

            focus.Select(0);
            focus.Cycle(1);
            focus.Clear();

            Assert.AreEqual(3, changes);
        }

        [Test]
        public void ReselectingTheSameComponentRaisesNothing()
        {
            var focus = new ComponentFocus();
            focus.SetOrder(Ids("a", "b"));
            focus.Select(0);
            int changes = 0;
            focus.Changed += () => changes++;

            focus.Select(0);
            focus.Clear();
            focus.Clear();

            Assert.AreEqual(1, changes);
        }

        [Test]
        public void CyclingAnEmptyListDoesNothing()
        {
            var focus = new ComponentFocus();

            focus.Cycle(1);

            Assert.IsFalse(focus.HasFocus);
        }
    }
}