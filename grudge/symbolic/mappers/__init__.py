"""Mappers to transform symbolic operators."""

from __future__ import division

__copyright__ = "Copyright (C) 2008 Andreas Kloeckner"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""


import six

import numpy as np
import pymbolic.primitives
import pymbolic.mapper.stringifier
import pymbolic.mapper.evaluator
import pymbolic.mapper.dependency
import pymbolic.mapper.substitutor
import pymbolic.mapper.constant_folder
import pymbolic.mapper.flop_counter
from pymbolic.mapper import CSECachingMapperMixin

from grudge import sym
import grudge.symbolic.operators as op


# {{{ mixins

class LocalOpReducerMixin(object):
    """Reduces calls to mapper methods for all local differentiation
    operators to a single mapper method, and likewise for mass
    operators.
    """
    # {{{ global differentiation
    def map_diff(self, expr, *args, **kwargs):
        return self.map_diff_base(expr, *args, **kwargs)

    def map_minv_st(self, expr, *args, **kwargs):
        return self.map_diff_base(expr, *args, **kwargs)

    def map_stiffness(self, expr, *args, **kwargs):
        return self.map_diff_base(expr, *args, **kwargs)

    def map_stiffness_t(self, expr, *args, **kwargs):
        return self.map_diff_base(expr, *args, **kwargs)

    def map_quad_stiffness_t(self, expr, *args, **kwargs):
        return self.map_diff_base(expr, *args, **kwargs)
    # }}}

    # {{{ global mass
    def map_mass_base(self, expr, *args, **kwargs):
        return self.map_elementwise_linear(expr, *args, **kwargs)

    def map_mass(self, expr, *args, **kwargs):
        return self.map_mass_base(expr, *args, **kwargs)

    def map_inverse_mass(self, expr, *args, **kwargs):
        return self.map_mass_base(expr, *args, **kwargs)

    def map_quad_mass(self, expr, *args, **kwargs):
        return self.map_mass_base(expr, *args, **kwargs)
    # }}}

    # {{{ reference differentiation
    def map_ref_diff(self, expr, *args, **kwargs):
        return self.map_ref_diff_base(expr, *args, **kwargs)

    def map_ref_stiffness_t(self, expr, *args, **kwargs):
        return self.map_ref_diff_base(expr, *args, **kwargs)

    def map_ref_quad_stiffness_t(self, expr, *args, **kwargs):
        return self.map_ref_diff_base(expr, *args, **kwargs)
    # }}}

    # {{{ reference mass
    def map_ref_mass_base(self, expr, *args, **kwargs):
        return self.map_elementwise_linear(expr, *args, **kwargs)

    def map_ref_mass(self, expr, *args, **kwargs):
        return self.map_ref_mass_base(expr, *args, **kwargs)

    def map_ref_inverse_mass(self, expr, *args, **kwargs):
        return self.map_ref_mass_base(expr, *args, **kwargs)

    def map_ref_quad_mass(self, expr, *args, **kwargs):
        return self.map_ref_mass_base(expr, *args, **kwargs)
    # }}}


class FluxOpReducerMixin(object):
    """Reduces calls to mapper methods for all flux
    operators to a smaller number of mapper methods.
    """
    def map_flux(self, expr, *args, **kwargs):
        return self.map_flux_base(expr, *args, **kwargs)

    def map_bdry_flux(self, expr, *args, **kwargs):
        return self.map_flux_base(expr, *args, **kwargs)

    def map_quad_flux(self, expr, *args, **kwargs):
        return self.map_flux_base(expr, *args, **kwargs)

    def map_quad_bdry_flux(self, expr, *args, **kwargs):
        return self.map_flux_base(expr, *args, **kwargs)


class OperatorReducerMixin(LocalOpReducerMixin, FluxOpReducerMixin):
    """Reduces calls to *any* operator mapping function to just one."""
    def _map_op_base(self, expr, *args, **kwargs):
        return self.map_operator(expr, *args, **kwargs)

    map_elementwise_linear = _map_op_base

    map_interpolation = _map_op_base

    map_nodal_sum = _map_op_base
    map_nodal_min = _map_op_base
    map_nodal_max = _map_op_base

    map_stiffness = _map_op_base
    map_diff = _map_op_base
    map_stiffness_t = _map_op_base

    map_ref_diff = _map_op_base
    map_ref_stiffness_t = _map_op_base

    map_mass = _map_op_base
    map_inverse_mass = _map_op_base
    map_ref_mass = _map_op_base
    map_ref_inverse_mass = _map_op_base

    map_opposite_interior_face_swap = _map_op_base
    map_face_mass_operator = _map_op_base
    map_ref_face_mass_operator = _map_op_base


class CombineMapperMixin(object):
    def map_operator_binding(self, expr):
        return self.combine([self.rec(expr.op), self.rec(expr.field)])


class IdentityMapperMixin(LocalOpReducerMixin, FluxOpReducerMixin):
    def map_operator_binding(self, expr, *args, **kwargs):
        assert not isinstance(self, BoundOpMapperMixin), \
                "IdentityMapper instances cannot be combined with " \
                "the BoundOpMapperMixin"

        return type(expr)(
                self.rec(expr.op, *args, **kwargs),
                self.rec(expr.field, *args, **kwargs))

    # {{{ operators

    def map_elementwise_linear(self, expr, *args, **kwargs):
        assert not isinstance(self, BoundOpMapperMixin), \
                "IdentityMapper instances cannot be combined with " \
                "the BoundOpMapperMixin"

        # it's a leaf--no changing children
        return expr

    map_interpolation = map_elementwise_linear

    map_nodal_sum = map_elementwise_linear
    map_nodal_min = map_elementwise_linear
    map_nodal_max = map_elementwise_linear

    map_stiffness = map_elementwise_linear
    map_diff = map_elementwise_linear
    map_stiffness_t = map_elementwise_linear

    map_ref_diff = map_elementwise_linear
    map_ref_stiffness_t = map_elementwise_linear

    map_mass = map_elementwise_linear
    map_inverse_mass = map_elementwise_linear
    map_ref_mass = map_elementwise_linear
    map_ref_inverse_mass = map_elementwise_linear

    map_opposite_interior_face_swap = map_elementwise_linear
    map_face_mass_operator = map_elementwise_linear
    map_ref_face_mass_operator = map_elementwise_linear

    # }}}

    # {{{ primitives

    def map_grudge_variable(self, expr, *args, **kwargs):
        # it's a leaf--no changing children
        return expr

    map_c_function = map_grudge_variable

    map_ones = map_grudge_variable
    map_node_coordinate_component = map_grudge_variable

    # }}}


class BoundOpMapperMixin(object):
    def map_operator_binding(self, expr, *args, **kwargs):
        return getattr(self, expr.op.mapper_method)(
                expr.op, expr.field, *args, **kwargs)

# }}}


# {{{ basic mappers

class CombineMapper(CombineMapperMixin, pymbolic.mapper.CombineMapper):
    pass


class DependencyMapper(
        CombineMapperMixin,
        pymbolic.mapper.dependency.DependencyMapper,
        OperatorReducerMixin):
    def __init__(self,
            include_operator_bindings=True,
            composite_leaves=None,
            **kwargs):
        if composite_leaves is False:
            include_operator_bindings = False
        if composite_leaves is True:
            include_operator_bindings = True

        pymbolic.mapper.dependency.DependencyMapper.__init__(self,
                composite_leaves=composite_leaves, **kwargs)

        self.include_operator_bindings = include_operator_bindings

    def map_operator_binding(self, expr):
        if self.include_operator_bindings:
            return set([expr])
        else:
            return CombineMapperMixin.map_operator_binding(self, expr)

    def map_operator(self, expr):
        return set()

    def map_grudge_variable(self, expr):
        return set([expr])

    def _map_leaf(self, expr):
        return set()

    map_ones = _map_leaf
    map_node_coordinate_component = _map_leaf


class FlopCounter(
        CombineMapperMixin,
        pymbolic.mapper.flop_counter.FlopCounter):
    def map_operator_binding(self, expr):
        return self.rec(expr.field)

    def map_scalar_parameter(self, expr):
        return 0

    def map_c_function(self, expr):
        return 1

    def map_ones(self, expr):
        return 0

    def map_node_coordinate_component(self, expr):
        return 0


class IdentityMapper(
        IdentityMapperMixin,
        pymbolic.mapper.IdentityMapper):
    pass


class SubstitutionMapper(pymbolic.mapper.substitutor.SubstitutionMapper,
        IdentityMapperMixin):
    pass


class CSERemover(IdentityMapper):
    def map_common_subexpression(self, expr):
        return self.rec(expr.child)

# }}}


# {{{ operator binder

class OperatorBinder(CSECachingMapperMixin, IdentityMapper):
    map_common_subexpression_uncached = \
            IdentityMapper.map_common_subexpression

    def map_product(self, expr):
        if len(expr.children) == 0:
            return expr

        from pymbolic.primitives import flattened_product, Product

        first = expr.children[0]
        if isinstance(first, op.Operator):
            prod = flattened_product(expr.children[1:])
            if isinstance(prod, Product) and len(prod.children) > 1:
                from warnings import warn
                warn("Binding '%s' to more than one "
                        "operand in a product is ambiguous - "
                        "use the parenthesized form instead."
                        % first)
            return sym.OperatorBinding(first, self.rec(prod))
        else:
            return first * self.rec(flattened_product(expr.children[1:]))

# }}}


# {{{ operator specializer

class OperatorSpecializer(CSECachingMapperMixin, IdentityMapper):
    """Guided by a typedict obtained through type inference (i.e. by
    :class:`grudge.symbolic.mappers.type_inference.TypeInferrrer`),
    substitutes more specialized operators for generic ones.

    For example, if type inference has determined that a differentiation
    operator is applied to an argument on a quadrature grid, this
    differentiation operator is then swapped out for a *quadrature*
    differentiation operator.
    """

    def __init__(self, typedict):
        """
        :param typedict: generated by
        :class:`grudge.symbolic.mappers.type_inference.TypeInferrer`.
        """
        self.typedict = typedict

    map_common_subexpression_uncached = \
            IdentityMapper.map_common_subexpression

    def map_operator_binding(self, expr):
        from grudge.symbolic.primitives import BoundaryPair

        from grudge.symbolic.mappers.type_inference import (
                type_info, QuadratureRepresentation)

        # {{{ figure out field type
        try:
            field_type = self.typedict[expr.field]
        except TypeError:
            # numpy arrays are not hashable
            # has_quad_operand remains unset

            assert isinstance(expr.field, np.ndarray)
        else:
            try:
                field_repr_tag = field_type.repr_tag
            except AttributeError:
                # boundary pairs are not assigned types
                assert isinstance(expr.field, BoundaryPair)
                has_quad_operand = False
            else:
                has_quad_operand = isinstance(field_repr_tag,
                            QuadratureRepresentation)
        # }}}

        # Based on where this is run in the symbolic operator processing
        # pipeline, we may encounter both reference and non-reference
        # operators.

        # {{{ elementwise operators

        if isinstance(expr.op, op.MassOperator) and has_quad_operand:
            return op.QuadratureMassOperator(
                    field_repr_tag.quadrature_tag)(self.rec(expr.field))

        elif isinstance(expr.op, op.RefMassOperator) and has_quad_operand:
            return op.RefQuadratureMassOperator(
                    field_repr_tag.quadrature_tag)(self.rec(expr.field))

        elif (isinstance(expr.op, op.StiffnessTOperator) and has_quad_operand):
            return op.QuadratureStiffnessTOperator(
                    expr.op.xyz_axis, field_repr_tag.quadrature_tag)(
                            self.rec(expr.field))

        elif (isinstance(expr.op, op.RefStiffnessTOperator)
                and has_quad_operand):
            return op.RefQuadratureStiffnessTOperator(
                    expr.op.xyz_axis, field_repr_tag.quadrature_tag)(
                            self.rec(expr.field))

        elif (isinstance(expr.op, op.QuadratureGridUpsampler)
                and isinstance(field_type, type_info.BoundaryVectorBase)):
            # potential shortcut:
            #if (isinstance(expr.field, OperatorBinding)
                    #and isinstance(expr.field.op, RestrictToBoundary)):
                #return QuadratureRestrictToBoundary(
                        #expr.field.op.tag, expr.op.quadrature_tag)(
                                #self.rec(expr.field.field))

            return op.QuadratureBoundaryGridUpsampler(
                    expr.op.quadrature_tag, field_type.boundary_tag)(expr.field)
        # }}}

        elif isinstance(expr.op, op.RestrictToBoundary) and has_quad_operand:
            raise TypeError("RestrictToBoundary cannot be applied to "
                    "quadrature-based operands--use QuadUpsample(Boundarize(...))")

        # {{{ flux operator specialization
        elif isinstance(expr.op, op.FluxOperatorBase):
            from pytools.obj_array import with_object_array_or_scalar

            repr_tag_cell = [None]

            def process_flux_arg(flux_arg):
                arg_repr_tag = self.typedict[flux_arg].repr_tag
                if repr_tag_cell[0] is None:
                    repr_tag_cell[0] = arg_repr_tag
                else:
                    # An error for this condition is generated by
                    # the type inference pass.

                    assert arg_repr_tag == repr_tag_cell[0]

            is_boundary = isinstance(expr.field, BoundaryPair)
            if is_boundary:
                bpair = expr.field
                with_object_array_or_scalar(process_flux_arg, bpair.field)
                with_object_array_or_scalar(process_flux_arg, bpair.bfield)
            else:
                with_object_array_or_scalar(process_flux_arg, expr.field)

            is_quad = isinstance(repr_tag_cell[0], QuadratureRepresentation)
            if is_quad:
                assert not expr.op.is_lift
                quad_tag = repr_tag_cell[0].quadrature_tag

            new_fld = self.rec(expr.field)
            flux = expr.op.flux

            if is_boundary:
                if is_quad:
                    return op.QuadratureBoundaryFluxOperator(
                            flux, quad_tag, bpair.tag)(new_fld)
                else:
                    return op.BoundaryFluxOperator(flux, bpair.tag)(new_fld)
            else:
                if is_quad:
                    return op.QuadratureFluxOperator(flux, quad_tag)(new_fld)
                else:
                    return op.FluxOperator(flux, expr.op.is_lift)(new_fld)
        # }}}

        else:
            return IdentityMapper.map_operator_binding(self, expr)

# }}}


# {{{ global-to-reference mapper

class GlobalToReferenceMapper(CSECachingMapperMixin, IdentityMapper):
    """Maps operators that apply on the global function space down to operators on
    reference elements, together with explicit multiplication by geometric factors.
    """

    def __init__(self, ambient_dim, dim=None):
        CSECachingMapperMixin.__init__(self)
        IdentityMapper.__init__(self)

        if dim is None:
            dim = ambient_dim

        self.ambient_dim = ambient_dim
        self.dim = dim

    map_common_subexpression_uncached = \
            IdentityMapper.map_common_subexpression

    def map_operator_binding(self, expr):
        # Global-to-reference is run after operator specialization, so
        # if we encounter non-quadrature operators here, we know they
        # must be nodal.

        jac_in = sym.area_element(self.ambient_dim, self.dim, dd=expr.op.dd_in)
        jac_noquad = sym.area_element(self.ambient_dim, self.dim,
                dd=expr.op.dd_in.with_qtag(sym.QTAG_NONE))

        def rewrite_derivative(ref_class, field,  dd_in, with_jacobian=True):
            jac_tag = sym.area_element(self.ambient_dim, self.dim, dd=dd_in)

            rec_field = self.rec(field)
            if with_jacobian:
                rec_field = jac_tag * rec_field
            return sum(
                    sym.inverse_metric_derivative(
                        rst_axis, expr.op.xyz_axis,
                        ambient_dim=self.ambient_dim, dim=self.dim) *
                    ref_class(rst_axis, dd_in=dd_in)(rec_field)
                    for rst_axis in range(self.dim))

        if isinstance(expr.op, op.MassOperator):
            return op.RefMassOperator(expr.op.dd_in, expr.op.dd_out)(
                    jac_in * self.rec(expr.field))

        elif isinstance(expr.op, op.InverseMassOperator):
            return op.RefInverseMassOperator(expr.op.dd_in, expr.op.dd_out)(
                1/jac_in * self.rec(expr.field))

        elif isinstance(expr.op, op.FaceMassOperator):
            jac_in_surf = - sym.area_element(self.ambient_dim, self.dim - 1,
                    dd=expr.op.dd_in)
            return op.RefFaceMassOperator(expr.op.dd_in, expr.op.dd_out)(
                    jac_in_surf * self.rec(expr.field))

        elif isinstance(expr.op, op.StiffnessOperator):
            return op.RefMassOperator()(jac_noquad *
                    self.rec(
                        op.DiffOperator(expr.op.xyz_axis)(expr.field)))

        elif isinstance(expr.op, op.DiffOperator):
            return rewrite_derivative(
                    op.RefDiffOperator,
                    expr.field, dd_in=expr.op.dd_in, with_jacobian=False)

        elif isinstance(expr.op, op.StiffnessTOperator):
            return rewrite_derivative(
                    op.RefStiffnessTOperator,
                    expr.field, dd_in=expr.op.dd_in)

        elif isinstance(expr.op, op.MInvSTOperator):
            return self.rec(
                    op.InverseMassOperator()(
                        op.StiffnessTOperator(expr.op.xyz_axis)(expr.field)))

        else:
            return IdentityMapper.map_operator_binding(self, expr)

# }}}


# {{{ stringification ---------------------------------------------------------

class StringifyMapper(pymbolic.mapper.stringifier.StringifyMapper):
    def _format_dd(self, dd):
        def fmt(s):
            if isinstance(s, type):
                return s.__name__
            else:
                return repr(s)

        from meshmode.discretization.connection import (
                FRESTR_ALL_FACES, FRESTR_INTERIOR_FACES)
        if dd.domain_tag is None:
            result = "?"
        elif dd.domain_tag is sym.DTAG_VOLUME_ALL:
            result = "vol"
        elif dd.domain_tag is sym.DTAG_SCALAR:
            result = "scalar"
        elif dd.domain_tag is FRESTR_ALL_FACES:
            result = "all_faces"
        elif dd.domain_tag is FRESTR_INTERIOR_FACES:
            result = "int_faces"
        else:
            result = fmt(dd.domain_tag)

        if dd.quadrature_tag is None:
            pass
        elif dd.quadrature_tag is sym.QTAG_NONE:
            result += "q"
        else:
            result += "Q"+fmt(dd.quadrature_tag)

        return result

    def _format_op_dd(self, op):
        return "[%s->%s]" % (self._format_dd(op.dd_in), self._format_dd(op.dd_out))

    # {{{ nodal ops

    def map_nodal_sum(self, expr, enclosing_prec):
        return "NodalSum" + self._format_op_dd(expr)

    def map_nodal_max(self, expr, enclosing_prec):
        return "NodalMax" + self._format_op_dd(expr)

    def map_nodal_min(self, expr, enclosing_prec):
        return "NodalMin" + self._format_op_dd(expr)

    # }}}

    # {{{ global differentiation

    def map_diff(self, expr, enclosing_prec):
        return "Diffx%d%s" % (expr.xyz_axis, self._format_op_dd(expr))

    def map_minv_st(self, expr, enclosing_prec):
        return "MInvSTx%d%s" % (expr.xyz_axis, self._format_op_dd(expr))

    def map_stiffness(self, expr, enclosing_prec):
        return "Stiffx%d%s" % (expr.xyz_axis, self._format_op_dd(expr))

    def map_stiffness_t(self, expr, enclosing_prec):
        return "StiffTx%d%s" % (expr.xyz_axis, self._format_op_dd(expr))

    # }}}

    # {{{ global mass

    def map_mass(self, expr, enclosing_prec):
        return "M"

    def map_inverse_mass(self, expr, enclosing_prec):
        return "InvM"

    # }}}

    # {{{ reference differentiation
    def map_ref_diff(self, expr, enclosing_prec):
        return "Diffr%d%s" % (expr.rst_axis, self._format_op_dd(expr))

    def map_ref_stiffness_t(self, expr, enclosing_prec):
        return "StiffTr%d%s" % (expr.rst_axis, self._format_op_dd(expr))

    # }}}

    # {{{ reference mass

    def map_ref_mass(self, expr, enclosing_prec):
        return "RefM" + self._format_op_dd(expr)

    def map_ref_inverse_mass(self, expr, enclosing_prec):
        return "RefInvM" + self._format_op_dd(expr)

    # }}}

    def map_elementwise_linear(self, expr, enclosing_prec):
        return "ElWLin:%s%s" % (
                expr.__class__.__name__,
                self._format_op_dd(expr))

    # {{{ flux

    def map_face_mass_operator(self, expr, enclosing_prec):
        return "FaceM" + self._format_op_dd(expr)

    def map_ref_face_mass_operator(self, expr, enclosing_prec):
        return "RefFaceM" + self._format_op_dd(expr)

    def map_opposite_interior_face_swap(self, expr, enclosing_prec):
        return "OppSwap" + self._format_op_dd(expr)

    # }}}

    def map_ones(self, expr, enclosing_prec):
        return "Ones" + self._format_op_props(expr)

    # {{{ geometry data

    def map_node_coordinate_component(self, expr, enclosing_prec):
        return "x[%d]@%s" % (expr.axis, self._format_dd(expr.dd))

    # }}}

    def map_operator_binding(self, expr, enclosing_prec):
        from pymbolic.mapper.stringifier import PREC_NONE
        return "<%s>(%s)" % (
                self.rec(expr.op, PREC_NONE),
                self.rec(expr.field, PREC_NONE))

    def map_c_function(self, expr, enclosing_prec):
        return expr.name

    def map_grudge_variable(self, expr, enclosing_prec):
        return "%s:%s" % (expr.name, self._format_dd(expr.dd))

    def map_interpolation(self, expr, enclosing_prec):
        return "Interp" + self._format_op_dd(expr)


class PrettyStringifyMapper(
        pymbolic.mapper.stringifier.CSESplittingStringifyMapperMixin,
        StringifyMapper):
    pass


class NoCSEStringifyMapper(StringifyMapper):
    def map_common_subexpression(self, expr, enclosing_prec):
        return self.rec(expr.child, enclosing_prec)

# }}}


# {{{ quadrature support

class QuadratureUpsamplerRemover(CSECachingMapperMixin, IdentityMapper):
    def __init__(self, quad_min_degrees, do_warn=True):
        IdentityMapper.__init__(self)
        CSECachingMapperMixin.__init__(self)
        self.quad_min_degrees = quad_min_degrees
        self.do_warn = do_warn

    map_common_subexpression_uncached = \
            IdentityMapper.map_common_subexpression

    def map_operator_binding(self, expr):
        if isinstance(expr.op, (op.QuadratureGridUpsampler,
                op.QuadratureInteriorFacesGridUpsampler,
                op.QuadratureBoundaryGridUpsampler)):
            try:
                min_degree = self.quad_min_degrees[expr.op.quadrature_tag]
            except KeyError:
                if self.do_warn:
                    from warnings import warn
                    warn("No minimum degree for quadrature tag '%s' specified--"
                            "falling back to nodal evaluation"
                            % expr.op.quadrature_tag)
                return self.rec(expr.field)
            else:
                if min_degree is None:
                    return self.rec(expr.field)
                else:
                    return expr.op(self.rec(expr.field))
        else:
            return IdentityMapper.map_operator_binding(self, expr)


class QuadratureDetector(CSECachingMapperMixin, CombineMapper):
    """For a given expression, this mapper returns the upsampling
    operator in effect at the root of the expression, or *None*
    if there isn't one.
    """
    class QuadStatusNotKnown:
        pass

    map_common_subexpression_uncached = \
            CombineMapper.map_common_subexpression

    def combine(self, values):
        from pytools import single_valued
        return single_valued([
            v for v in values if v is not self.QuadStatusNotKnown])

    def map_variable(self, expr):
        return None

    def map_constant(self, expr):
        return self.QuadStatusNotKnown

    def map_operator_binding(self, expr):
        if isinstance(expr.op, (
                op.DiffOperatorBase, op.FluxOperatorBase,
                op.MassOperatorBase)):
            return None
        elif isinstance(expr.op, (op.QuadratureGridUpsampler,
                op.QuadratureInteriorFacesGridUpsampler)):
            return expr.op
        else:
            return CombineMapper.map_operator_binding(self, expr)


class QuadratureUpsamplerChanger(CSECachingMapperMixin, IdentityMapper):
    """This mapper descends the expression tree, down to each
    quadrature-consuming operator (diff, mass) along each branch.
    It then change
    """
    def __init__(self, desired_quad_op):
        IdentityMapper.__init__(self)
        CSECachingMapperMixin.__init__(self)

        self.desired_quad_op = desired_quad_op

    map_common_subexpression_uncached = \
            IdentityMapper.map_common_subexpression

    def map_operator_binding(self, expr):
        if isinstance(expr.op, (
                op.DiffOperatorBase, op.FluxOperatorBase,
                op.MassOperatorBase)):
            return expr
        elif isinstance(expr.op, (op.QuadratureGridUpsampler,
                op.QuadratureInteriorFacesGridUpsampler)):
            return self.desired_quad_op(expr.field)
        else:
            return IdentityMapper.map_operator_binding(self, expr)

# }}}


# {{{ simplification / optimization

class CommutativeConstantFoldingMapper(
        pymbolic.mapper.constant_folder.CommutativeConstantFoldingMapper,
        IdentityMapperMixin):

    def __init__(self):
        pymbolic.mapper.constant_folder\
                .CommutativeConstantFoldingMapper.__init__(self)
        self.dep_mapper = DependencyMapper()

    def is_constant(self, expr):
        return not bool(self.dep_mapper(expr))

    def map_operator_binding(self, expr):
        field = self.rec(expr.field)

        from grudge.tools import is_zero
        if is_zero(field):
            return 0

        return expr.op(field)


class EmptyFluxKiller(CSECachingMapperMixin, IdentityMapper):
    def __init__(self, mesh):
        IdentityMapper.__init__(self)
        self.mesh = mesh

    map_common_subexpression_uncached = \
            IdentityMapper.map_common_subexpression

    def map_operator_binding(self, expr):
        from meshmode.mesh import is_boundary_tag_empty
        if (isinstance(expr.op, sym.InterpolationOperator)
                and expr.op.dd_out.is_boundary()
                and expr.op.dd_out.domain_tag not in [
                    sym.FRESTR_ALL_FACES, sym.FRESTR_INTERIOR_FACES]
                and is_boundary_tag_empty(self.mesh,
                    expr.op.dd_out.domain_tag)):
            return 0
        else:
            return IdentityMapper.map_operator_binding(self, expr)


class _InnerDerivativeJoiner(pymbolic.mapper.RecursiveMapper):
    def map_operator_binding(self, expr, derivatives):
        if isinstance(expr.op, op.DifferentiationOperator):
            derivatives.setdefault(expr.op, []).append(expr.field)
            return 0
        else:
            return DerivativeJoiner()(expr)

    def map_common_subexpression(self, expr, derivatives):
        # no use preserving these if we're moving derivatives around
        return self.rec(expr.child, derivatives)

    def map_sum(self, expr, derivatives):
        from pymbolic.primitives import flattened_sum
        return flattened_sum(tuple(
            self.rec(child, derivatives) for child in expr.children))

    def map_product(self, expr, derivatives):
        from grudge.symbolic.tools import is_scalar
        from pytools import partition
        scalars, nonscalars = partition(is_scalar, expr.children)

        if len(nonscalars) != 1:
            return DerivativeJoiner()(expr)
        else:
            from pymbolic import flattened_product
            factor = flattened_product(scalars)
            nonscalar, = nonscalars

            sub_derivatives = {}
            nonscalar = self.rec(nonscalar, sub_derivatives)

            def do_map(expr):
                if is_scalar(expr):
                    return expr
                else:
                    return self.rec(expr, derivatives)

            for operator, operands in six.iteritems(sub_derivatives):
                for operand in operands:
                    derivatives.setdefault(operator, []).append(
                            factor*operand)

            return factor*nonscalar

    def map_constant(self, expr, *args):
        return DerivativeJoiner()(expr)

    def map_scalar_parameter(self, expr, *args):
        return DerivativeJoiner()(expr)

    def map_if_positive(self, expr, *args):
        return DerivativeJoiner()(expr)

    def map_power(self, expr, *args):
        return DerivativeJoiner()(expr)

    # these two are necessary because they're forwarding targets
    def map_algebraic_leaf(self, expr, *args):
        return DerivativeJoiner()(expr)

    def map_quotient(self, expr, *args):
        return DerivativeJoiner()(expr)

    map_node_coordinate_component = map_algebraic_leaf


class DerivativeJoiner(CSECachingMapperMixin, IdentityMapper):
    """Joins derivatives:

    .. math::

        \frac{\partial A}{\partial x} + \frac{\partial B}{\partial x}
        \rightarrow
        \frac{\partial (A+B)}{\partial x}.
    """
    map_common_subexpression_uncached = \
            IdentityMapper.map_common_subexpression

    def map_sum(self, expr):
        idj = _InnerDerivativeJoiner()

        def invoke_idj(expr):
            sub_derivatives = {}
            result = idj(expr, sub_derivatives)
            if not sub_derivatives:
                return expr
            else:
                for operator, operands in six.iteritems(sub_derivatives):
                    derivatives.setdefault(operator, []).extend(operands)

                return result

        derivatives = {}
        new_children = [invoke_idj(child)
                for child in expr.children]

        for operator, operands in six.iteritems(derivatives):
            new_children.insert(0, operator(
                sum(self.rec(operand) for operand in operands)))

        from pymbolic.primitives import flattened_sum
        return flattened_sum(new_children)


class _InnerInverseMassContractor(pymbolic.mapper.RecursiveMapper):
    def __init__(self, outer_mass_contractor):
        self.outer_mass_contractor = outer_mass_contractor
        self.extra_operator_count = 0

    def map_constant(self, expr):
        from grudge.tools import is_zero

        if is_zero(expr):
            return 0
        else:
            return op.OperatorBinding(
                    op.InverseMassOperator(),
                    self.outer_mass_contractor(expr))

    def map_algebraic_leaf(self, expr):
        return op.OperatorBinding(
                op.InverseMassOperator(),
                self.outer_mass_contractor(expr))

    def map_operator_binding(self, binding):
        if isinstance(binding.op, op.MassOperator):
            return binding.field
        elif isinstance(binding.op, op.StiffnessOperator):
            return op.DifferentiationOperator(binding.op.xyz_axis)(
                    self.outer_mass_contractor(binding.field))
        elif isinstance(binding.op, op.StiffnessTOperator):
            return op.MInvSTOperator(binding.op.xyz_axis)(
                    self.outer_mass_contractor(binding.field))
        elif isinstance(binding.op, op.FluxOperator):
            assert not binding.op.is_lift

            return op.FluxOperator(binding.op.flux, is_lift=True)(
                    self.outer_mass_contractor(binding.field))
        elif isinstance(binding.op, op.BoundaryFluxOperator):
            assert not binding.op.is_lift

            return op.BoundaryFluxOperator(binding.op.flux,
                    binding.op.boundary_tag, is_lift=True)(
                        self.outer_mass_contractor(binding.field))
        else:
            self.extra_operator_count += 1
            return op.InverseMassOperator()(
                self.outer_mass_contractor(binding))

    def map_sum(self, expr):
        return expr.__class__(tuple(self.rec(child) for child in expr.children))

    def map_product(self, expr):
        def is_scalar(expr):
            return isinstance(expr, (int, float, complex, sym.ScalarParameter))

        from pytools import len_iterable
        nonscalar_count = len_iterable(ch
                for ch in expr.children
                if not is_scalar(ch))

        if nonscalar_count > 1:
            # too complicated, don't touch it
            self.extra_operator_count += 1
            return op.InverseMassOperator()(
                    self.outer_mass_contractor(expr))
        else:
            def do_map(expr):
                if is_scalar(expr):
                    return expr
                else:
                    return self.rec(expr)
            return expr.__class__(tuple(
                do_map(child) for child in expr.children))


class InverseMassContractor(CSECachingMapperMixin, IdentityMapper):
    # assumes all operators to be bound
    map_common_subexpression_uncached = \
            IdentityMapper.map_common_subexpression

    def map_operator_binding(self, binding):
        # we only care about bindings of inverse mass operators

        if isinstance(binding.op, op.InverseMassOperator):
            iimc = _InnerInverseMassContractor(self)
            proposed_result = iimc(binding.field)
            if iimc.extra_operator_count > 1:
                # We're introducing more work than we're saving.
                # Don't perform the simplification
                return binding.op(self.rec(binding.field))
            else:
                return proposed_result
        else:
            return binding.op(self.rec(binding.field))

# }}}


# {{{ error checker

class ErrorChecker(CSECachingMapperMixin, IdentityMapper):
    map_common_subexpression_uncached = \
            IdentityMapper.map_common_subexpression

    def __init__(self, mesh):
        self.mesh = mesh

    def map_operator_binding(self, expr):
        if isinstance(expr.op, op.DiffOperatorBase):
            if (self.mesh is not None
                    and expr.op.xyz_axis >= self.mesh.dim):
                raise ValueError("optemplate tries to differentiate along a "
                        "non-existent axis (e.g. Z in 2D)")

        # FIXME: Also check fluxes
        return IdentityMapper.map_operator_binding(self, expr)

    def map_normal(self, expr):
        if self.mesh is not None and expr.axis >= self.mesh.dimensions:
            raise ValueError("optemplate tries to differentiate along a "
                    "non-existent axis (e.g. Z in 2D)")

        return expr

# }}}


# {{{ collectors for various symbolic operator components

class CollectorMixin(OperatorReducerMixin, LocalOpReducerMixin, FluxOpReducerMixin):
    def combine(self, values):
        from pytools import flatten
        return set(flatten(values))

    def map_constant(self, expr, *args, **kwargs):
        return set()

    map_grudge_variable = map_constant
    map_c_function = map_grudge_variable

    map_ones = map_grudge_variable
    map_node_coordinate_component = map_grudge_variable

    map_operator = map_grudge_variable


# I'm not sure this works still.
#class GeometricFactorCollector(CollectorMixin, CombineMapper):
#    pass


class BoundOperatorCollector(CSECachingMapperMixin, CollectorMixin, CombineMapper):
    def __init__(self, op_class):
        self.op_class = op_class

    map_common_subexpression_uncached = \
            CombineMapper.map_common_subexpression

    def map_operator_binding(self, expr):
        if isinstance(expr.op, self.op_class):
            result = set([expr])
        else:
            result = set()

        return result | CombineMapper.map_operator_binding(self, expr)


class FluxExchangeCollector(CSECachingMapperMixin, CollectorMixin, CombineMapper):
    map_common_subexpression_uncached = \
            CombineMapper.map_common_subexpression

    def map_flux_exchange(self, expr):
        return set([expr])

# }}}


# {{{ evaluation

class Evaluator(pymbolic.mapper.evaluator.EvaluationMapper):
    pass

# }}}


# vim: foldmethod=marker